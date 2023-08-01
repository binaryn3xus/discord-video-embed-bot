import io
from urllib.parse import urlparse

import instaloader

from downloader import base


class InstagramClient(base.BaseClient):
    DOMAINS = ['instagram.com', 'ddinstagram.com']

    def __init__(self, url: str):
        super(InstagramClient, self).__init__(url=url)
        self.client = instaloader.Instaloader()
        self.id = urlparse(url).path.strip('/').split('/')[-1]

    async def download(self) -> io.BytesIO:
        post = instaloader.Post.from_shortcode(self.client.context, self.id)

        with self.client.context._session.get(post.video_url) as resp:
            return (
                self.MESSAGE.format(
                    url=self.url,
                    description=post.title or post.caption,
                    likes=post.likes,
                ),
                io.BytesIO(resp.content),
            )
