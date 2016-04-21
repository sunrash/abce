# Copyright 2012 Davoud Taghawi-Nejad
#
# Module Author: Davoud Taghawi-Nejad
#
# ABCE is open-source software. If you are using ABCE for your research you are
# requested the quote the use of this software.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License and quotation of the
# author. You may obtain a copy of the License at
#       http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations under
# the License.
"""
The :py:class:`abce.Agent` class is the basic class for creating your agents. It automatically handles the
possession of goods of an agent. In order to produce/transforme goods you also need to subclass
the :py:class:`abce.Firm` or to create a consumer the :py:class:`abce.Household`.

For detailed documentation on:

Trading, see :doc:`Trade`

Logging and data creation, see :doc:`Database` and :doc:`simulation_results`

Messaging between agents, see :doc:`Messaging`.



"""
from __future__ import division
from collections import OrderedDict, defaultdict
import numpy as np
save_err = np.seterr(invalid='ignore')
from database import Database
from networklogger import NetworkLogger
from trade import Trade, Offer
from messaging import Messaging, Message
import time
from copy import copy
import random
from abce.expiringgood import ExpiringGood
from pprint import pprint
import traceback
import random
from abce.notenoughgoods import NotEnoughGoods


class Agent(Database, NetworkLogger, Trade, Messaging):
    """ Every agent has to inherit this class. It connects the agent to the simulation
    and to other agent. The :class:`abceagent.Trade`, :class:`abceagent.Database` and
    :class:`abceagent.Messaging` classes are included. You can enhance an agent, by also
    inheriting from :class:`abceagent.Firm`.:class:`abceagent.FirmMultiTechnologies`
    or :class:`abceagent.Household`.

    For example::

        class Household(abceagent.Agent, abceagent.Household):
            def init(self, simulation_parameters, agent_parameters):
                ...
    """
    def __init__(self, idn, group, trade_logging, database, logger, random_seed):
        """ Do not overwrite __init__ instead use a method called init instead.
        init is called whenever the agent are build.
        """
        self.idn = idn
        """ self.idn returns the agents idn READ ONLY"""
        self.name = '%s_%i:' % (group, idn)
        """ self.name returns the agents name, which is the group name and the
        id seperated by '_' e.G. "household_12" READ ONLY!
        """
        self.name_without_colon = '%s_%i' % (group, idn)
        self.group = group
        """ self.group returns the agents group or type READ ONLY! """
        #TODO should be group_address(group), but it would not work
        # when fired manual + ':' and manual group_address need to be removed
        self._out = []
        """ The simulation parameters and the number of agents in other groups

         Useful entries:

            'rounds':
                 the total number of rounds in the simulation.
        """
        self.database_connection = database
        self.logger_connection = logger

        if trade_logging == 'individual':
            self.trade_logging = 1
        elif trade_logging == 'group':
            self.trade_logging = 2
        elif trade_logging == 'off':
            self.trade_logging = 0
        else:
            SystemExit('trade_logging wrongly defined in agent.__init__' + trade_logging)

        self._haves = defaultdict(float)

        #TODO make defaultdict; delete all key errors regarding self._haves as defaultdict, does not have missing keys
        self._haves['money'] = 0
        self._msgs = {}

        self.given_offers = OrderedDict()
        self._open_offers = defaultdict(dict)
        self._offer_count = 0
        self._reject_offers_retrieved_end_subround = []
        self._contract_requests = defaultdict(list)
        self._contract_offers = defaultdict(list)
        self._contracts_pay = defaultdict(list)
        self._contracts_deliver = defaultdict(list)
        self._contracts_payed = []
        self._contracts_delivered = []

        self._expiring_goods = []

        self._trade_log = defaultdict(int)
        self._data_to_observe = {}
        self._data_to_log_1 = {}
        self._quotes = {}
        self.round = 0
        """ self.round returns the current round in the simulation READ ONLY!"""
        self._perishable = []
        self._resources = []
        self.variables_to_track_panel = []
        self.variables_to_track_aggregate = []

        random.seed(random_seed)

    def init(self, parameters, agent_parameters):
        """ This method is called when the agents are build.
        It can be overwritten by the user, to initialize the agents.
        parameters and agent_parameters are the parameters given in
        :py:meth:`abce.Simulation.build_agents`
        """
        pass

    def possession(self, good):
        """ returns how much of good an agent possesses.

        Returns:
            A number.

        possession does not return a dictionary for self.log(...), you can use self.possessions([...])
        (plural) with self.log.

        Example:

            if self.possession('money') < 1:
                self.financial_crisis = True

            if not(is_positive(self.possession('money')):
                self.bancrupcy = True

        """
        return float(self._haves[good])


    def possessions(self):
        """ returns all possessions """
        return copy(self._haves)

    def _offer_counter(self):
        """ returns a unique number for an offer (containing the agent's name)
        """
        self._offer_count += 1
        return hash((self.name, self._offer_count))

    def _advance_round(self):
        for offer in self.given_offers.values():
            if offer['made'] < self.round:
                print("in agent %s this offers have not been retrieved:" % self.name_without_colon)
                for offer in self.given_offers.values():
                    if offer['made'] < self.round:
                        print(offer.__repr__())
                raise Exception('%s_%i: There are offers have been made before'
                                 'last round and not been retrieved in this'
                                 'round get_offer(.)' % (self.group, self.idn))

        # contracts
        self._contract_requests = defaultdict(list)
        self._contract_offers = defaultdict(list)
        self._contracts_payed = []
        self._contracts_delivered = []

        for good in self._contracts_deliver:
            self._contracts_deliver[good] = [contract for contract in self._contracts_deliver[good] if contract['end_date'] > self.round]

        for good in self._contracts_pay:
            self._contracts_pay[good] = [contract for contract in self._contracts_pay[good] if contract['end_date'] > self.round]
        # expiring goods
        for good in self._expiring_goods:
            self._haves[good]._advance_round()

        if self.trade_logging > 0:
            self.database_connection.put(["trade_log", self._trade_log, self.round])

        self._trade_log = defaultdict(int)

        if sum([len(offers) for offers in self._open_offers.values()]):
                pprint(dict(self._open_offers))
                raise SystemExit('%s_%i: There are offers an agent send that have not'
                                 'been retrieved in this round get_offer(.)' % (self.group, self.idn))

        if sum([len(offers) for offers in self._msgs.values()]):
                pprint(dict(self._msgs))
                raise SystemExit('%s_%i: There are messages an agent send that have not'
                                 'been retrieved in this round get_messages(.)' % (self.group, self.idn))

        self.round += 1

    def create(self, good, quantity):
        """ creates quantity of the good out of nothing

        Use create with care, as long as you use it only for labor and
        natural resources your model is macro-economically complete.

        Args:
            'good': is the name of the good
            quantity: number
        """
        self._haves[good] += quantity

    def create_timestructured(self, good, quantity):
        """ creates quantity of the time structured good out of nothing.
        For example::

            self.creat_timestructured('capital', [10,20,30])

        Creates capital. 10 units are 2 years old 20 units are 1 year old
        and 30 units are new.

        It can alse be used with a quantity instead of an array. In this
        case the amount is equally split on the years.::

            self.creat_timestructured('capital', 60)

        In this case 20 units are 2 years old 20 units are 1 year old
        and 20 units are new.

        Args:
            'good':
                is the name of the good

            quantity:
                an arry or number
        """
        length = len(self._haves[good].time_structure)
        try:
            for i in range(length):
                self._haves[good].time_structure[i] += quantity[i]
        except TypeError:
            for i in range(length):
                self._haves[good].time_structure[i] += quantity / length


    def _declare_expiring(self, good, duration):
        """ creates a good that has a limited duration
        """
        self._haves[good] = ExpiringGood(duration)
        self._expiring_goods.append(good)

    def destroy(self, good, quantity=None):
        """ destroys quantity of the good. If quantity is omitted destroys all

        Args::

            'good':
                is the name of the good
            quantity (optional):
                number

        Raises::

            NotEnoughGoods: when goods are insufficient
        """
        if quantity is None:
            self._haves[good] = 0
        else:
            self._haves[good] -= quantity
            if self._haves[good] < 0:
                self._haves[good] = 0
                raise NotEnoughGoods(self.name, good, quantity - self._haves[good])

    def get_group(self):
        return self.group

    def get_id(self):
        return self.idn

    def _set_network_drawing_frequency(self, frequency):
        self._network_drawing_frequency = frequency

    def _execute(self, command, incomming_messages):
        self._out = []
        try:
            self._clearing__end_of_subround(incomming_messages)
            getattr(self, command)()
            self.__reject_polled_but_not_accepted_offers()
        except KeyboardInterrupt:
            return None
        except:
            time.sleep(random.random())
            traceback.print_exc()
            raise

        return self._out

    def _register_resource(self, resource, units, product):
        self._resources.append((resource, units, product))

    def _produce_resource(self):
        for resource, units, product in self._resources:
            if resource in self._haves:
                try:
                    self._haves[product] += float(units) * self._haves[resource]
                except KeyError:
                    self._haves[product] = float(units) * self._haves[resource]

    def _register_perish(self, good):
        self._perishable.append(good)

    def _perish(self):
        for good in self._perishable:
            if good in self._haves:
                self._haves[good] = 0

    def _register_panel(self, possessions, variables):
        self.possessions_to_track_panel = possessions
        self.variables_to_track_panel = variables

    def _register_aggregate(self, possessions, variables):
        self.possessions_to_track_aggregate = possessions
        self.variables_to_track_aggregate = variables

    def panel(self):
        """ use in action list to create panel data """
        data_to_track = {}
        for possession in self.possessions_to_track_panel:
            data_to_track[possession] = self._haves[possession]

        for variable in self.variables_to_track_panel:
            data_to_track[variable] = self.__dict__[variable]
        self.database_connection.put(["panel",
                                       data_to_track,
                                       str(self.idn),
                                       self.group,
                                       str(self.round)])

    def aggregate(self):
        """ use in action list to create data """
        data_to_track = {}
        for possession in self.possessions_to_track_aggregate:
            data_to_track[possession] = self._haves[possession]

        for variable in self.variables_to_track_aggregate:
            data_to_track[variable] = self.__dict__[variable]
        self.database_connection.put(["aggregate",
                                       data_to_track,
                                       self.group,
                                       self.round])

    def __reject_polled_but_not_accepted_offers(self):
        to_reject = []
        for offers in self._open_offers.values():
            for offer in offers.values():
                if offer['open_offer_status'] == 'polled':
                    to_reject.append(offer)
        for offer in to_reject:
            self.reject(offer)


    def _send(self, receiver_group, receiver_idn, typ, msg):
        """ sends a message to 'receiver_group', who can be an agent, a group or
        'all'. The agents receives it at the begin of each round in
        self.messages(typ) is 'm' for mails.
        typ =(_o,c,u,r) are
        reserved for internally processed offers.
        """
        self._out.append((receiver_group, receiver_idn, (typ, msg)))

    def _send_to_group(self, receiver_group, typ, msg):
        """ sends a message to 'receiver_group', who can be an agent, a group or
        'all'. The agents receives it at the begin of each round in
        self.messages(typ) is 'm' for mails.
        typ =(_o,c,u,r) are
        reserved for internally processed offers.
        """
        raise NotImplementedError
        self._out.append([receiver_group, 'all', (typ, msg)])

def flatten(d, parent_key=''):
    items = []
    for k, v in d.items():
        try:
            items.extend(flatten(v, '%s%s_' % (parent_key, k)).items())
        except AttributeError:
            items.append(('%s%s' % (parent_key, k), v))
    return dict(items)

