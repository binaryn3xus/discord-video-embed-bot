import asyncio
import datetime
import logging
import typing
from functools import partial

import discord
from discord import app_commands
from discord import ui
from discord.app_commands import checks

from bot import constants
from bot import domain
from bot import service
from bot.common import utils

"""
This file needs to be refactored at some point.
Logic needs to be split so we can easily add support for another server type
without duplicating business logic. This is basically service layer code.
"""


class CustomView(ui.View):
    @ui.button(label='❌')
    async def on_click(
        self,
        interaction: discord.Interaction,
        _: ui.Button,
    ) -> None:
        if interaction.user.mentioned_in(interaction.message):
            await interaction.message.delete()
            logging.info(f'User {interaction.user.id} performed a delete action')
        else:
            logging.warning(
                f'User {interaction.user.id} tried to perform an illegal delete action on {interaction.message.id}'
            )


class DiscordClient(discord.Client):
    def __init__(self, *, intents: discord.Intents, **options: typing.Any) -> None:
        super().__init__(intents=intents, **options)

        commands = [
            app_commands.Command(
                name='embed',
                description='Embeds media directly into discord',
                callback=self.command_embed,
            ),
            app_commands.Command(
                name='help',
                description='Prints configuration for this server',
                callback=self.command_help,
            ),
            app_commands.Command(
                name='silence',
                description='(Un)Ban a user from using embed commands',
                callback=self.silence_user,
            ),
        ]

        self.tree = app_commands.CommandTree(client=self)
        for command in commands:
            self.tree.add_command(command)

    async def on_ready(self):
        await self.tree.sync()
        logging.info(f'Logged on as {self.user}')

    async def on_message(self, message: discord.Message):  # noqa: C901
        if message.author == self.user:
            return

        url = utils.find_first_url(message.content)
        if not url:
            return

        if service.should_handle_url(url) is False:
            return

        new_message = (await asyncio.gather(message.delete(), message.channel.send('🔥 Working on it 🥵')))[1]

        try:
            post = await service.get_post(
                url=url,
                server_vendor=constants.ServerVendor.DISCORD,
                server_uid=str(message.guild.id),
                author_uid=str(message.author.id),
            )
        except Exception as e:
            logging.error(f'Failed downloading {url}: {str(e)}')
            await asyncio.gather(
                new_message.edit(
                    content=f'{message.author.mention}\nFailed downloading {url}.\nError: {str(e)}.',
                    suppress=True,
                ),
                new_message.add_reaction('❌'),
            )
            return

        try:
            msg = await self._send_post(post=post, send_func=message.channel.send, author=message.author)
            logging.info(f'User {message.author.display_name} sent message with url {url}')
        except Exception as e:
            logging.error(f'Failed sending message {url}: {str(e)}')
            msg = await message.channel.send(
                content=f'Failed sending discord message for {url} ({message.author.mention}).\nError: {str(e)}'
            )

        await asyncio.gather(msg.add_reaction('❌'), new_message.delete())

    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        if (
            reaction.message.author.id == self.user.id
            and reaction.emoji == '❌'
            and user.mentioned_in(message=reaction.message)
            and reaction.message.created_at.replace(tzinfo=None)
            >= (datetime.datetime.utcnow() - datetime.timedelta(minutes=5))
        ):
            logging.info(f'User {user.display_name} deleted message {utils.find_first_url(reaction.message.content)}')
            await reaction.message.delete()

    async def command_embed(self, interaction: discord.Interaction, url: str, spoiler: bool = False) -> None:
        await interaction.response.defer()

        if service.should_handle_url(url) is False:
            return

        try:
            post = service.get_post(
                url=url,
                server_vendor=constants.ServerVendor.DISCORD,
                server_uid=str(interaction.guild.id),
                author_uid=str(interaction.user.id),
            )
            if not post.spoiler:
                post.spoiler = spoiler
        except Exception as e:
            logging.error(f'Failed downloading {url}: {str(e)}')
            await interaction.followup.send(
                content=f'Failed fetching {url} ({interaction.user.mention}).\nError: {str(e)}',
                view=CustomView(),
            )
            raise e

        await self._send_post(
            post=post,
            send_func=partial(interaction.followup.send, view=CustomView()),
            author=interaction.user,
        )

    async def command_help(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        response = service.get_server_info(
            server_vendor=constants.ServerVendor.DISCORD,
            server_uid=str(interaction.guild.id),
        )
        if not response:
            await interaction.followup.send(
                content='Failed retreiving server configuration.',
                view=CustomView(),
            )
            return

        await interaction.followup.send(content=f'{interaction.user.mention}\n{response}', view=CustomView())

    @checks.has_permissions(administrator=True)
    async def silence_user(self, interaction: discord.Interaction, member: discord.Member, unban: bool = False) -> None:
        await interaction.response.defer(ephemeral=True)

        if interaction.user.guild.id == member.id:
            response = 'Can\'t ban yourself..'
        else:
            try:
                service.change_server_member_banned_status(
                    server_vendor=constants.ServerVendor.DISCORD,
                    server_uid=interaction.guild.id,
                    user_uid=member.id,
                    banned=not unban,
                )
                response = 'User {display_name} {banned}banned.'
            except Exception as e:
                logging.error(f'Failed banning user... {str(e)}')
                response = 'Failed to {banned}ban user {display_name}.'

            response = response.format(
                display_name=member.display_name,
                banned='un' if unban else '',
            )

        await interaction.followup.send(
            content=response,
            ephemeral=True,
        )

    async def _send_post(
        self,
        post: domain.Post,
        send_func: typing.Callable,
        author: discord.User,
    ) -> discord.Message:
        send_kwargs = {
            'suppress_embeds': True,
        }
        file = None
        if post.buffer:
            extension = utils.guess_extension_from_buffer(buffer=post.buffer)
            file = discord.File(
                fp=post.buffer,
                filename='{spoiler}file{extension}'.format(
                    spoiler='SPOILER_' if post.spoiler else '',
                    extension=extension,
                ),
            )
            send_kwargs['file'] = file

        try:
            content = f'Here you go {author.mention} {utils.random_emoji()}.\n{str(post)}'
            if len(content) > 2000:
                if post.spoiler:
                    content = content[:1995] + '||...'
                else:
                    content = content[:1997] + '...'

            send_kwargs['content'] = content

            return await send_func(**send_kwargs)
        except discord.HTTPException as e:
            if e.status != 413:  # Payload too large
                raise e
            logging.info('File too large, resizing...')
            file.fp.seek(0)
            post.buffer = await utils.resize(buffer=file.fp, extension=extension)
            return await self._send_post(post=post, send_func=send_func, author=author)
