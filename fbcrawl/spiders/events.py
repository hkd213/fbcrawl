import scrapy
import logging

from scrapy.loader import ItemLoader
from scrapy.http import FormRequest
from fbcrawl.items import EventItem


class EventsSpider(scrapy.Spider):
    """
    Parse FB comments, given a post (needs credentials)
    """
    name = "events"
    custom_settings = {
        'FEED_EXPORT_FIELDS': ['eventID', 'name', 'location', 'link', 'details', 'image', 'realDate'],
        'DUPEFILTER_CLASS': 'scrapy.dupefilters.BaseDupeFilter',
        'CONCURRENT_REQUESTS': 1,
    }

    def __init__(self, *args, **kwargs):
        # turn off annoying logging, set LOG_LEVEL=DEBUG in settings.py to see more logs
        logger = logging.getLogger('scrapy.middleware')
        logger.setLevel(logging.WARNING)
        super().__init__(*args, **kwargs)

        # email & pass need to be passed as attributes!
        if 'email' not in kwargs or 'password' not in kwargs:
            raise AttributeError('You need to provide valid email and password:\n'
                                 'scrapy fb -a email="EMAIL" -a password="PASSWORD"')
        else:
            self.logger.info('Email and password provided, using these as credentials')

        # page name parsing (added support for full urls)
        if 'page' not in kwargs:
            raise AttributeError('You need to provide a valid page name to crawl!'
                                 'scrapy fb -a page="PAGENAME"')
        elif self.page.find('https://www.facebook.com/') != -1:
            self.page = self.page[25:]
            self.logger.info('Page attribute provided, scraping "{}"'.format(self.page))
        elif self.page.find('https://mbasic.facebook.com/') != -1:
            self.page = self.page[28:]
            self.logger.info('Page attribute provided, scraping "{}"'.format(self.page))
        elif self.page.find('https://m.facebook.com/') != -1:
            self.page = self.page[23:]
            self.logger.info('Page attribute provided, scraping "{}"'.format(self.page))
        else:
            self.logger.info('Page attribute provided, scraping "{}"'.format(self.page))

        # parse year
        if 'year' not in kwargs:
            self.year = 2019
            self.logger.info('Year attribute not found, set scraping back to {}'.format(self.year))
        else:
            assert int(self.year) <= 2019 and int(self.year) >= 2006, \
                'Year must be an int number 2006 <= year <= 2019'
            self.year = int(self.year)  # arguments are passed as strings
            self.logger.info('Year attribute found, set scraping back to {}'.format(self.year))

        # parse lang, if not provided (but is supported) it will be guessed in parse_home
        if 'lang' not in kwargs:
            self.logger.info('Language attribute not provided, I will try to guess it from the fb interface')
            self.logger.info('To specify, add the lang parameter: scrapy fb -a lang="LANGUAGE"')
            self.logger.info('Currently choices for "LANGUAGE" are: "en", "es", "fr", "it", "pt"')
            self.lang = '_'
        elif self.lang == 'en' or self.lang == 'es' or self.lang == 'fr' or self.lang == 'it' or self.lang == 'pt':
            self.logger.info('Language attribute recognized, using "{}" for the facebook interface'.format(self.lang))
        else:
            self.logger.info('Lang "{}" not currently supported'.format(self.lang))
            self.logger.info('Currently supported languages are: "en", "es", "fr", "it", "pt"')
            self.logger.info('Change your interface lang from facebook and try again')
            raise AttributeError('Language provided not currently supported')

        # current year, this variable is needed for parse_page recursion
        self.k = 2019
        # count number of posts, used to prioritized parsing and correctly insert in the csv
        self.count = 0

        self.start_urls = ['https://mbasic.facebook.com']

    def parse(self, response):
        '''
        Handle login with provided credentials
        '''
        return FormRequest.from_response(
            response,
            formxpath='//form[contains(@action, "login")]',
            formdata={'email': self.email, 'pass': self.password},
            callback=self.parse_home
        )

    def parse_home(self, response):
        '''
        This method has multiple purposes:
        1) Handle failed logins due to facebook 'save-device' redirection
        2) Set language interface, if not already provided
        3) Navigate to given page
        '''
        # handle 'save-device' redirection
        if response.xpath("//div/a[contains(@href,'save-device')]"):
            self.logger.info('Got stuck in "save-device" checkpoint')
            self.logger.info('I will now try to redirect to the correct page')
            return FormRequest.from_response(
                response,
                formdata={'name_action_selected': 'dont_save'},
                callback=self.parse_home
            )

        # set language interface
        if self.lang == '_':
            if response.xpath("//input[@placeholder='Search Facebook']"):
                self.logger.info('Language recognized: lang="en"')
                self.lang = 'en'
            elif response.xpath("//input[@placeholder='Buscar en Facebook']"):
                self.logger.info('Language recognized: lang="es"')
                self.lang = 'es'
            elif response.xpath("//input[@placeholder='Rechercher sur Facebook']"):
                self.logger.info('Language recognized: lang="fr"')
                self.lang = 'fr'
            elif response.xpath("//input[@placeholder='Cerca su Facebook']"):
                self.logger.info('Language recognized: lang="it"')
                self.lang = 'it'
            elif response.xpath("//input[@placeholder='Pesquisa no Facebook']"):
                self.logger.info('Language recognized: lang="pt"')
                self.lang = 'pt'
            else:
                raise AttributeError('Language not recognized\n'
                                     'Change your interface lang from facebook '
                                     'and try again')

        # navigate to provided page
        href = response.urljoin(self.page)
        href = href + '?v=events'
        self.logger.info('Scraping facebook page {}'.format(href))

        return scrapy.Request(url=href, callback=self.parse_page, meta={'index': 1})

    def parse_page(self, response):
        '''
        Parse the given page selecting the posts.
        Then ask recursively for another page.
        '''
        # select all posts
        for post in response.xpath("//div[contains(@class,'bx')]"):
            new = ItemLoader(item=EventItem(), selector=post)
            self.logger.info('Parsing event n = {}'.format(abs(self.count)))
            new.add_xpath('url', ".//a[contains(@aria-label, ' ')]/@href")

            # page_url #new.add_value('url',response.url)
            # returns full post-link in a list


            post = post.xpath(".//a[contains(@aria-label, ' ')]/@href").extract()
            temp_post = response.urljoin(post[0])
            self.count -= 1
            yield scrapy.Request(temp_post, self.parse_post, priority=self.count, meta={'item': new})

            # load following page
        # tries to click on "more", otherwise it looks for the appropriate
        # year for 1-click only and proceeds to click on others
        # new_page = response.xpath(
        #     "//div[2]/a[contains(@href,'timestart=') and not(contains(text(),'ent')) and not(contains(text(),number()))]/@href").extract()
        # if not new_page:
        #     if response.meta['flag'] == self.k and self.k >= self.year:
        #         self.logger.info('There are no more, flag set at = {}'.format(self.k))
        #         xpath = "//div/a[contains(@href,'time') and contains(text(),'" + str(self.k) + "')]/@href"
        #         new_page = response.xpath(xpath).extract()
        #         if new_page:
        #             new_page = response.urljoin(new_page[0])
        #             self.k -= 1
        #             self.logger.info('Everything OK, new flag: {}'.format(self.k))
        #             yield scrapy.Request(new_page, callback=self.parse_page, meta={'flag': self.k})
        #         else:
        #             while not new_page:  # sometimes the years are skipped
        #                 self.logger.info('XPATH not found for year {}'.format(self.k - 1))
        #                 self.k -= 1
        #                 self.logger.info('Trying with previous year, flag={}'.format(self.k))
        #                 if self.k < self.year:
        #                     self.logger.info(
        #                         'The previous year to crawl is less than the parameter year: {} < {}'.format(self.k,
        #                                                                                                      self.year))
        #                     self.logger.info(
        #                         'This is not handled well, please re-run with -a year="{}" or less'.format(self.k))
        #                     break
        #                 xpath = "//div/a[contains(@href,'time') and contains(text(),'" + str(self.k) + "')]/@href"
        #                 new_page = response.xpath(xpath).extract()
        #             self.logger.info('New page found with flag {}'.format(self.k))
        #             new_page = response.urljoin(new_page[0])
        #             self.k -= 1
        #             self.logger.info('Now going with flag {}'.format(self.k))
        #             yield scrapy.Request(new_page, callback=self.parse_page, meta={'flag': self.k})
        #     else:
        #         self.logger.info('Crawling has finished with no errors!')
        # else:
        #     new_page = response.urljoin(new_page[0])
        #     if 'flag' in response.meta:
        #         self.logger.info('Page scraped, click on more! flag = {}'.format(response.meta['flag']))
        #         yield scrapy.Request(new_page, callback=self.parse_page, meta={'flag': response.meta['flag']})
        #     else:
        #         self.logger.info('FLAG DOES NOT ALWAYS REPRESENT ACTUAL YEAR')
        #         self.logger.info('First page scraped, click on more! Flag not set, default flag = {}'.format(self.k))
        #         yield scrapy.Request(new_page, callback=self.parse_page, meta={'flag': self.k})

    def parse_post(self, response):
        new = ItemLoader(item=EventItem(), response=response, parent=response.meta['item'])
        new.add_xpath('eventID', "//input[contains(@name, 'target')]/@value")
        new.add_xpath('name', "//title/text()")
        new.add_xpath('realDate','//div[contains(@id, "event_summary")]/div/div[1]/@title')
        new.add_xpath('location','//div[contains(@id, "event_summary")]/div/div[2]/@title | '
                                 '//div[contains(@id, "event_summary")]/div/div[2]//dd/div/text()')
        new.add_xpath('link', '//link[contains(@rel, "canonical")]/@href')
        new.add_xpath('details', './/div[contains(text(), "Details")]/../../../div[last()]')
        new.add_xpath('image', './/div[contains(@id, "event_header")]//img/@src')

        yield new.load_item()
