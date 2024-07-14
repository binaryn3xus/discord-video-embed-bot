import datetime
import io
import typing

from django.db import transaction

from bot import cache
from bot import constants
from bot import domain
from bot import models


def create_server(
    vendor_uid: str,
    vendor: constants.ServerVendor,
    owner_id: typing.Optional[int] = None,
    tier: constants.ServerTier = constants.ServerTier.FREE,
    status: constants.ServerStatus = constants.ServerStatus.ACTIVE,
) -> domain.Server:
    with transaction.atomic():
        server = models.Server.objects.create(
            vendor_uid=vendor_uid,
            vendor=vendor,
            tier=tier,
            status=status,
            owner_id=owner_id,
        )
        # Add some default integrations to server
        integrations = models.ServerIntegration.objects.bulk_create(
            [
                models.ServerIntegration(
                    integration=constants.Integration.INSTAGRAM,
                    enabled=True,
                    server_id=server.pk,
                ),
                models.ServerIntegration(
                    integration=constants.Integration.TIKTOK,
                    enabled=True,
                    server_id=server.pk,
                ),
                models.ServerIntegration(
                    integration=constants.Integration.YOUTUBE,
                    enabled=True,
                    server_id=server.pk,
                ),
            ]
        )

    server = domain.Server(
        uid=server.uid,
        vendor_uid=server.vendor_uid,
        vendor=server.vendor,
        tier=server.tier,
        tier_valid_until=server.tier_valid_until,
        status=server.status,
        prefix=server.prefix,
        integrations={
            integration.integration: domain.Integration(
                uid=integration.uid,
                integration=integration.integration,
                enabled=integration.enabled,
            )
            for integration in integrations
        },
        _internal_id=server.pk,
    )
    cache.set(key=cache.CacheKey.SERVER, value=server)

    return server


def get_number_of_posts_in_server_from_datetime(
    server_id: int,
    from_datetime: datetime.datetime,
) -> int:
    post_cnt = cache.get(cache.CacheKey.SERVER_POST_COUNT)
    if post_cnt is not cache.NO_HIT:
        return post_cnt

    post_cnt = models.ServerPost.objects.filter(
        server_id=server_id,
        created__gt=from_datetime,
    ).count()
    cache.set(key=cache.CacheKey.SERVER_POST_COUNT, value=post_cnt, override_timeout=60)

    return post_cnt


def update_post_format(
    vendor: constants.ServerVendor,
    vendor_uid: str,
    integration: constants.Integration,
    post_format: str,
) -> None:
    models.ServerIntegration.objects.filter(
        server__vendor=vendor,
        server__vendor_uid=vendor_uid,
        integration=integration,
    ).update(post_format=post_format)

    cache.delete(cache.CacheKey.SERVER)


def get_server(
    vendor: constants.ServerVendor,
    vendor_uid: str,
    status: constants.ServerStatus = constants.ServerStatus.ACTIVE,
) -> typing.Optional[domain.Server]:
    server = cache.get(key=cache.CacheKey.SERVER)
    if server is not cache.NO_HIT:
        return server

    server = (
        models.Server.objects.filter(
            vendor=vendor,
            vendor_uid=vendor_uid,
            status=status,
        )
        .prefetch_related('integrations')
        .first()
    )

    if not server:
        return None

    server = domain.Server(
        uid=server.uid,
        vendor_uid=server.vendor_uid,
        vendor=server.vendor,
        tier=server.tier,
        tier_valid_until=server.tier_valid_until,
        status=server.status,
        prefix=server.prefix,
        integrations={
            integration.integration: domain.Integration(
                uid=integration.uid,
                integration=integration.integration,
                enabled=integration.enabled,
                post_format=integration.post_format,
            )
            for integration in server.integrations.all()
        },
        _internal_id=server.pk,
    )
    cache.set(key=cache.CacheKey.SERVER, value=server)

    return server


def get_post(
    url: str,
    integration: constants.Integration,
    integration_uid: str,
    integration_index: typing.Optional[int] = None,
) -> typing.Optional[domain.Post]:
    post = models.Post.objects.filter(
        integration=integration,
        integration_uid=integration_uid,
        integration_index=integration_index,
    ).first()

    if post is None:
        return None

    return domain.Post(
        url=url,
        author=post.author,
        description=post.description,
        views=post.views,
        likes=post.likes,
        buffer=io.BytesIO(post.blob) if post.blob else None,
        spoiler=post.spoiler,
        created=post.posted_at,
        _internal_id=post.pk,
    )


def save_post(
    post: domain.Post,
    integration: constants.Integration,
    integration_uid: str,
    integration_index: typing.Optional[int] = None,
) -> models.Post:
    return models.Post.objects.create(
        integration=integration,
        integration_uid=integration_uid,
        integration_index=integration_index,
        author=post.author,
        description=post.description,
        views=post.views,
        likes=post.likes,
        spoiler=post.spoiler,
        posted_at=post.created,
        blob=post.read_buffer(),
    )


def save_server_post(
    server_vendor: constants.ServerVendor,
    server_uid: str,
    author_uid: str,
    post: domain.Post,
    integration: constants.Integration,
    integration_uid: str,
    integration_index: typing.Optional[int] = None,
) -> None:
    server = models.Server.objects.filter(
        vendor=server_vendor,
        vendor_uid=server_uid,
    ).first()
    if not server:
        raise Exception('Server does not exist?!')

    if post._internal_id is not None:
        models.ServerPost.objects.create(
            author_uid=author_uid,
            url=post.url,
            server=server,
            post_id=post._internal_id,
        )
        cache.increment(cache.CacheKey.SERVER_POST_COUNT)
        return

    with transaction.atomic():
        post_model = save_post(
            post=post,
            integration=integration,
            integration_uid=integration_uid,
            integration_index=integration_index,
        )
        models.ServerPost.objects.create(
            author_uid=author_uid,
            url=post.url,
            server=server,
            post=post_model,
        )
        cache.increment(cache.CacheKey.SERVER_POST_COUNT)
