# Define here the models for your spider middleware
#
# See documentation in:
# https://docs.scrapy.org/en/latest/topics/spider-middleware.html

from scrapy import signals

# useful for handling different item types with a single interface
from itemadapter import is_item, ItemAdapter


class NseScraperSpiderMiddleware:
    # Not all methods need to be defined. If a method is not defined,
    # scrapy acts as if the spider middleware does not modify the
    # passed objects.

    @classmethod
    def from_crawler(cls, crawler):
        # This method is used by Scrapy to create your spiders.
        s = cls()
        crawler.signals.connect(s.spider_opened, signal=signals.spider_opened)
        return s

    def process_spider_input(self, response, spider):
        # Called for each response that goes through the spider
        # middleware and into the spider.

        # Should return None or raise an exception.
        return None

    def process_spider_output(self, response, result, spider):
        # Called with the results returned from the Spider, after
        # it has processed the response.

        # Must return an iterable of Request, or item objects.
        for i in result:
            yield i

    def process_spider_exception(self, response, exception, spider):
        # Called when a spider or process_spider_input() method
        # (from other spider middleware) raises an exception.

        # Should return either None or an iterable of Request or item objects.
        pass

    def process_start_requests(self, start_requests, spider):
        # Called with the start requests of the spider, and works
        # similarly to the process_spider_output() method, except
        # that it doesn’t have a response associated.

        # Must return only requests (not items).
        for r in start_requests:
            yield r

    def spider_opened(self, spider):
        spider.logger.info('Spider opened: %s' % spider.name)


class NseScraperDownloaderMiddleware:
    # Not all methods need to be defined. If a method is not defined,
    # scrapy acts as if the downloader middleware does not modify the
    # passed objects.

    # Spiders whose requests may be routed through an outbound proxy, mapped to the
    # setting holding that proxy URL. afx.kwayisi.org refuses connections from this
    # host on every one of its addresses, so its traffic can optionally be proxied.
    PROXY_SETTING_BY_SPIDER = {
        'afx_scraper': 'AFX_PROXY_URL',
    }

    def __init__(self, settings=None):
        self.settings = settings

    @classmethod
    def from_crawler(cls, crawler):
        # This method is used by Scrapy to create your spiders.
        s = cls(settings=crawler.settings)
        crawler.signals.connect(s.spider_opened, signal=signals.spider_opened)
        return s

    def process_request(self, request, spider):
        # Called for each request that goes through the downloader
        # middleware.

        # Must either:
        # - return None: continue processing this request
        # - or return a Response object
        # - or return a Request object
        # - or raise IgnoreRequest: process_exception() methods of
        #   installed downloader middleware will be called
        proxy_url = self._proxy_for(spider)
        if proxy_url and 'proxy' not in request.meta:
            request.meta['proxy'] = proxy_url
        return None

    def _proxy_for(self, spider):
        """Proxy URL configured for this spider, or None to leave requests untouched."""
        if self.settings is None:
            return None
        setting_name = self.PROXY_SETTING_BY_SPIDER.get(getattr(spider, 'name', None))
        if not setting_name:
            return None
        return (self.settings.get(setting_name) or '').strip() or None

    # process_response/process_exception are intentionally not defined: Scrapy skips
    # undefined hooks, and the generated no-op versions used a deprecated signature.

    def spider_opened(self, spider):
        spider.logger.info('Spider opened: %s' % spider.name)
