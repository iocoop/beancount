__author__ = "Martin Blais <blais@furius.ca>"

import re

from beancount.parser import cmptest
from beancount.plugins import implicit_prices
from beancount.plugins import unique_prices
from beancount import loader


class TestValidateAmbiguousPrices(cmptest.TestCase):

    @loader.load_doc()
    def test_validate_unique_prices__different(self, entries, errors, options_map):
        """
        2000-01-01 price HOOL 500.00 USD
        2000-01-01 price HOOL 500.01 USD
        """
        self.assertEqual([], errors)
        _, valid_errors = unique_prices.validate_unique_prices(entries, options_map)
        self.assertEqual([unique_prices.UniquePricesError], list(map(type, valid_errors)))
        self.assertTrue(re.search('Disagreeing price', valid_errors[0].message))

    @loader.load_doc()
    def test_validate_unique_prices__same(self, entries, errors, options_map):
        """
        2000-01-01 price HOOL 500.00 USD
        2000-01-01 price HOOL 500.00 USD
        """
        self.assertEqual([], errors)
        _, valid_errors = unique_prices.validate_unique_prices(entries, options_map)
        self.assertEqual([], valid_errors)

    @loader.load_doc()
    def test_validate_unique_prices__from_costs(self, entries, errors, options_map):
        """
        2014-01-01 open Income:Misc
        2014-01-01 open Assets:Account1
        2014-01-01 open Liabilities:Account1

        2014-01-15 *
          Income:Misc        -201 USD
          Assets:Account1       1 HOUSE {100 USD}
          Liabilities:Account1  1 HOUSE {101 USD}
        """
        self.assertEqual([], errors)
        new_entries, errors = implicit_prices.add_implicit_prices(entries, options_map)
        self.assertEqual([], errors)
        _, valid_errors = unique_prices.validate_unique_prices(new_entries, options_map)
        self.assertEqual([unique_prices.UniquePricesError], list(map(type, valid_errors)))
        self.assertTrue(re.search('Disagreeing price ent', valid_errors[0].message))
