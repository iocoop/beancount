"""A position object.

This container defines a "Lot" object, which is a triple of

  (currency, cost, lot-date)

where

  'currency' is the underlying types of units held,
  'cost': is an instance of Amount (number and currency) expressing the cost of
          this position, which is possibly None if the currency is not held at cost,
  'lot-date': which is the date of acquisition of the Lot (also optional and possibly None).

A "Position" represents a specific number of units of an associated lot:

  (number, lot)

"""
__author__ = "Martin Blais <blais@furius.ca>"

import datetime
import logging
import collections
import re

# Note: this file is mirrorred into ledgerhub. Relative imports only.
from beancount.core.number import ZERO
from beancount.core.number import Decimal
from beancount.core.number import NUMBER_RE
from beancount.core.number import D
from beancount.core.amount import Amount
from beancount.core.amount import NULL_AMOUNT
from beancount.core.amount import amount_mult
from beancount.core.amount import CURRENCY_RE
from beancount.core.display_context import DEFAULT_FORMATTER

# pylint: disable=invalid-name
NoneType = type(None)


# Lots are a representations of a commodity with an optional associated cost and
# optional acquisition date. (There are considered immutable and shared between
# many objects; this makes everything much faster.)
#
# Attributes:
#  currency: A string, the currency of this lot. May NOT be null.
#  cost: An Amount, or None if this lot has no associated cost.
#  lot_date: A datetime.date, or None if this lot has no associated date.
Lot = collections.namedtuple('Lot', 'currency cost lot_date')


# LotSpec is a temporary data structure for holding a lot specification before
# it gets resolved to an actual lot. This record should only be present in the
# intermediate state between parsing and booking.
#
# Attributes:
#   compound_cost: An instance of CompountAmount, possibly with empty values.
#   lot_date: A datetime.date instance.
#   label: A label string, or None.
#   merge: A boolean, true if we shoud be merging the cost basis before/after
#     the given posting.
LotSpec = collections.namedtuple('LotSpec',
                                 'currency compound_cost lot_date label merge')


def lot_currency_pair(lot):
    """Return the currency pair associated with a lot.

    Args:
      lot: An instance of Lot.
    Returns:
      A pair of a currency string and a cost currency string or None.
    """
    return (lot.currency,
            lot.cost.currency if lot.cost else None)


# Lookup for ordering a list of currencies: we want the majors first, then the
# cross-currencies, and then all the rest of the stuff a user might define
# (shorter strings first).
CURRENCY_ORDER = {
    'USD': 0,
    'EUR': 1,
    'JPY': 2,
    'CAD': 3,
    'GBP': 4,
    'AUD': 5,
    'NZD': 6,
    'CHF': 7,
    # All the rest in alphabetical order...
}

NCURRENCIES = len(CURRENCY_ORDER)


class Position:
    """A 'Position' is a specific number of units of a lot.
    This is used to track inventories.

    Attributes:
      lot: An instance of Lot (see above), the lot of this position.
      number: A Decimal object, the number of units of 'lot'.
    """
    __slots__ = ('lot', 'number')

    def __init__(self, lot, number):
        """Constructor from a lot and a number of units of the ot.

        Args:
          lot: The lot of this position.
          number: An instance of Decimal, the number of units of lot.
        """
        assert isinstance(lot, (Lot, LotSpec)), (
            "Expected a lot; received '{}'".format(lot))
        assert isinstance(number, (NoneType, Decimal)), (
            "Expected a Decimal; received '{}'".format(number))
        self.lot = lot
        self.number = number

    def __hash__(self):
        """Compute a hash for this position.

        Returns:
          A hash of this position object.
        """
        return hash((self.lot, self.number))

    def to_string(self, dformat=DEFAULT_FORMATTER, detail=True):
        """Render the position to a string.

        Args:
          dformat: An instance of DisplayFormatter.
          detail: A boolean, true if we should only render the lot details
           beyond the cost (lot-date, label, etc.). If false, we only render
           the cost, if present.
        Returns:
          A string, the rendered position.
        """
        lot = self.lot

        # Render the units.
        pos_str = Amount(self.number, lot.currency).to_string(dformat)

        # Render the cost (and other lot parameters, lot-date, label, etc.).
        if detail:
            if isinstance(lot, Lot):
                if lot.cost or lot.lot_date:
                    cost_str_list = []
                    cost_str_list.append('{')
                    if lot.cost:
                        cost_str_list.append(
                            Amount(lot.cost.number, lot.cost.currency).to_string(dformat))
                    if lot.lot_date:
                        cost_str_list.append(', {}'.format(lot.lot_date))
                    cost_str_list.append('}')
                    pos_str = '{} {}'.format(pos_str, ''.join(cost_str_list))
            else:
                assert isinstance(lot, LotSpec)
                pos_str = str(lot)
        else:
            # Render just the cost, if present.
            if lot.cost is not None:
                pos_str = '{} {{{}}}'.format(pos_str, lot.cost.to_string(dformat))

        return pos_str

    def __str__(self):
        """Return a string representation of the position.

        Returns:
          A string, a printable representation of the position.
        """
        return self.to_string()

    __repr__ = __str__

    def __eq__(self, other):
        """Equality comparison with another Position. The objects are considered equal
        if both number and lot are matching, and if the number of units is zero
        and the other position is None, that is also okay.

        Args:
          other: An instance of Position, or None.
        Returns:
          A boolean, true if the positions are equal.
        """
        if other is None:
            return self.number == ZERO
        else:
            return (self.number == other.number and
                    self.lot == other.lot)

    def sortkey(self):
        """Return a key to sort positions by. This key depends on the order of the
        currency of the lot (we want to order common currencies first) and the
        number of units.

        Returns:
          A tuple, used to sort lists of positions.
        """
        lot = self.lot
        currency = lot.currency
        order_units = CURRENCY_ORDER.get(currency, NCURRENCIES + len(currency))
        return (order_units, lot.cost or NULL_AMOUNT, self.number)

    def __lt__(self, other):
        """A least-than comparison operator for positions.

        Args:
          other: Another instance of Position.
        Returns:
          True if this positions is smaller than the other position.
        """
        return self.sortkey() < other.sortkey()

    def __copy__(self):
        """Shallow copy, except for the lot, which can be shared. This is important for
        performance reasons; a lot of time is spent here during balancing.

        Returns:
          A shallow copy of this position.
        """
        # Note: We use Decimal() for efficiency.
        return Position(self.lot, Decimal(self.number))

    def get_units(self):
        """Get the Amount that correponds to this lot. The amount is the number of units
        of the currency, irrespective of its cost or lot date.

        Returns:
          An instance of Amount.
        """
        return Amount(self.number, self.lot.currency)

    def get_cost(self):
        """Return the cost associated with this position. The cost is the number of
        units of the lot times the cost of the lot. If the lot has no associated
        cost, the amount of the position is returned as its cost.

        Returns:
          An instance of Amount.
        """
        cost = self.lot.cost
        if cost is None:
            return Amount(self.number, self.lot.currency)
        else:
            return amount_mult(cost, self.number)

    def get_weight(self, price=None):
        """Compute the weight of the position, with the given price.

        Returns:
          An instance of Amount.
        """
        # It the self has a cost, use that to balance this posting.
        lot = self.lot
        if lot.cost is not None:
            amount = amount_mult(lot.cost, self.number)

        # If there is a price, use that to balance this posting.
        elif price is not None:
            assert self.lot.currency != price.currency, (
                "Invalid currency for price: {} in {}".format(self, price))
            amount = amount_mult(price, self.number)

        # Otherwise, just use the units.
        else:
            amount = Amount(self.number, self.lot.currency)

        return amount

    def cost(self):
        """Return a Position representing the cost of this position. See get_cost().

        Returns:
          An instance of Position if there is a cost, or itself, if the position
          has no associated cost. Since we consider the Position object to be
          immutable and associated operations never modify an existing Position
          instance, it is legit to return this object itself.
        """
        cost = self.lot.cost
        if cost is None:
            return self
        else:
            return Position(Lot(cost.currency, None, None),
                            self.number * cost.number)

    def add(self, number):
        """Add a number of units to this position.

        Args:
          number: A Decimal instance, the number of units to add to this position.
        """
        # Note: Checks for positions going negative do not belong here, but
        # rather belong in the inventory.
        assert isinstance(number, Decimal)
        self.number += number

    def get_negative(self):
        """Get a copy of this position but with a negative number.

        Returns:
          An instance of Position which represents the inserse of this Position.
        """
        # Note: We use Decimal() for efficiency.
        return Position(self.lot, Decimal(-self.number))

    __neg__ = get_negative

    def is_negative_at_cost(self):
        """Return true if the position is held at cost and negative.

        Returns:
          A boolean.
        """
        return (self.number < ZERO and
                (self.lot.cost or self.lot.lot_date))

    @staticmethod
    def from_string(string):
        """Create a position from a string specification.

        This is a miniature parser used for building tests.

        Args:
          string: A string of <number> <currency> with an optional {<number>
            <currency>} for the cost, similar to the parser syntax.
        Returns:
          A new instance of Position.
        """
        match = re.match(
            (r'\s*({})\s+({})'
             r'(?:\s+{{([^}}]*)}})?'
             r'\s*$').format(NUMBER_RE, CURRENCY_RE),
            string)
        if not match:
            raise ValueError("Invalid string for position: '{}'".format(string))

        number = D(match.group(1))
        currency = match.group(2)

        # Parse a cost expression.
        cost, lot_date = None, None
        cost_expression = match.group(3)
        if match.group(3):
            expressions = [expr.strip() for expr in re.split('[,/]', cost_expression)]
            for expr in expressions:

                # Match a compound number.
                match = re.match(r'({})\s*(?:#\s*({}))?\s+({})$'.format(
                    NUMBER_RE, NUMBER_RE, CURRENCY_RE), expr)
                if match:
                    per_number, total_number, cost_currency = match.group(1, 2, 3)
                    per_number = D(per_number) if per_number else ZERO
                    total_number = D(total_number) if total_number else ZERO
                    if total_number:
                        # Calculate the per-unit cost.
                        total = number * per_number + total_number
                        per_number = total / number
                    cost = Amount(per_number, cost_currency)
                    continue

                # Match a date.
                match = re.match(r'(\d\d\d\d)[-/](\d\d)[-/](\d\d)$', expr)
                if match:
                    lot_date = datetime.date(*map(int, match.group(1, 2, 3)))
                    continue

                # Match a label.
                match = re.match(r'"([^"]+)*"$', expr)
                if match:
                    # label = match.groups(1)
                    logging.warning("Label not supported yet.")
                    continue

                # Match a merge-cost marker.
                match = re.match(r'\*$', expr)
                if match:
                    # merge = True
                    logging.warning("Merge-code not supported yet.")
                    continue

                raise ValueError("Invalid cost component: '{}'".format(expr))

        return Position(Lot(currency, cost, lot_date), D(number))

    @staticmethod
    def from_amounts(amount, cost_amount=None):
        """Create a position from an amount and a cost.

        Args:
          amount: An amount, that represents the number of units and the lot currency.
          cost_amount: If not None, represents the cost amount.
        Returns:
          A Position instance.
        """
        return Position(Lot(amount.currency, cost_amount, None), amount.number)


# pylint: disable=invalid-name
from_string = Position.from_string
from_amounts = Position.from_amounts
