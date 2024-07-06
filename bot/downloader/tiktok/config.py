from bot.downloader import base


class TiktokConfig(base.BaseClientConfig):
    """
    No additional settings for Tiktok integration
    """


class TiktokConfigSchema(base.BaseClientConfigSchema):
    _CONFIG_CLASS = TiktokConfig