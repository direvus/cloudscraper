#!/usr/bin/env python
""" lib/cloudtrax.py

 CloudTrax class for CloudScraper

 Copyright (c) 2013 The Goulburn Group. All Rights Reserved.

 http://www.goulburngroup.com.au

 Written by Alex Ferrara <alex@receptiveit.com.au>

"""

from BeautifulSoup import BeautifulSoup
from lib.node import Node
from lib.user import User
import cStringIO
import logging
import requests
import texttable
import Image


#
# Helper functions
#

def draw_table(entity_type, entities):
    """Draws a text table representation of the data supplied"""

    header = {'gateway': ['Name\n(mac)',
                          'Users',
                          'DL MB\nUL MB',
                          'Up\n(Down)',
                          'IP Address\n(Firmware)'],
              'relay': ['Name\n(mac)',
                        'Users',
                        'DL MB\nUL MB',
                        'Gateway\n(Firmware)',
                        'Up\n(Down)',
                        'Latency\n(Hops)'],
              'spare': ['Name\n(mac)',
                        'Users',
                        'DL MB\nUL MB',
                        'Up\n(Down)',
                        'IP Address\n(Firmware)']}

    table = texttable.Texttable()
    table.header(header[entity_type])

    for entity in entities:
        if entity.get_type() == entity_type:
            table.add_row(entity.get_table_row())


    return table.draw()

def distill_html(content, element, identifier):
    """Accept some HTML and return the filtered output"""
    distilled_text = []

    if element == 'table':
        distilled_table = BeautifulSoup(content).find(element, identifier)

        for row in distilled_table.findAll('tr'):
            raw_values = []

            for cell in row.findAll('td'):
                raw_values.append(cell.findAll(text=True))

            # Watch out for blank rows
            if len(raw_values) > 0:
                # Create a new node object for each node in the network
                distilled_text.append(raw_values)

    return distilled_text

def percentage(value, max_value):
    """Returns a float representing the percentage that
       value is of max_value"""

    return (float(value) * 100) / max_value


class CloudTrax:
    """CloudTrax connector class"""

    def __init__(self, config):
        """Constructor"""
        self.nodes = []
        self.users = []

        self.session = requests.session()

        logging.info('Verbose output is turned on')

        self.url = config.get_url()
        self.network = config.get_network()


    def login(self):
        """Method to login and create a web session"""

        logging.info('Logging in to CloudTrax Dashboard')

        parameters = {'account': self.network['username'],
                      'password': self.network['password'],
                      'status': 'View Status'}

        try:
            request = self.session.post(self.url['login'], data=parameters)
            request.raise_for_status()

        except requests.exceptions.HTTPError:
            logging.error('There was a HTTP error')
            exit(1)
        except requests.exceptions.ConnectionError:
            logging.error('There was a connection error')
            exit(1)

        return self.session

    def get_checkin_data(self, node_mac):
        """Scrape checkin information on the current node"""

        parameters = {'mac': node_mac,
                      'legend': '0'}

        logging.info('Requesting node checkin status for ' + node_mac)

        request = self.session.get(self.url['checkin'], params=parameters)

        colour_counter = {'cccccc': 0, '1faa5f': 0, '4fdd8f': 0}

        checkin_img = Image.open(cStringIO.StringIO(request.content))

        row = 1

        pixelmap = checkin_img.load()

        for col in range(0, checkin_img.size[0]):
            pixel_colour = str("%x%x%x" % (pixelmap[col, row][0],
                                           pixelmap[col, row][1],
                                           pixelmap[col, row][2]))

            if pixel_colour in colour_counter.keys():
                colour_counter[pixel_colour] += 1
            else:
                colour_counter[pixel_colour] = 1

        # Convert number of pixels into a percent
        time_as_gw = percentage(colour_counter['1faa5f'],
                                checkin_img.size[0] - 2)
        time_as_relay = percentage(colour_counter['4fdd8f'],
                                   checkin_img.size[0] - 2)
        time_offline = percentage(colour_counter['cccccc'],
                                  checkin_img.size[0] - 2)

        return (time_as_gw, time_as_relay, time_offline)

    def get_session(self):
        """Return session id"""
        return self.session

    def get_nodes(self):
        """Return a list of nodes"""

        # Refresh the network status if the nodes list is empty
        if len(self.nodes) == 0:
            logging.info('Refreshing node status from CloudTrax')
            self.refresh_nodes()

        return self.nodes

    def get_users(self):
        """Return network status"""
        if len(self.users) == 0:
            logging.info('Refreshing user statistics from CloudTrax')
            self.refresh_users()

        return self.users

    def refresh_nodes(self):
        """Return network information scraped from CloudTrax"""
        self.nodes = []

        parameters = {'network': self.network['name'],
                      'showall': '1',
                      'details': '1'}
    
        logging.info('Requesting network status') 

        request = self.session.get(self.url['data'], params=parameters)

        logging.info('Received network status ok') 

        if request.status_code == 200:
            for raw_values in distill_html(request.content, 'table',
                                           {'id': 'mytable'}):
                self.nodes.append(Node(raw_values,
                    self.get_checkin_data(raw_values[2][0])))

        else:
            logging.error('Request failed') 
            exit(request.status_code)

        return self.nodes

    def refresh_users(self):
        """Return a list of wifi user statistics scraped from CloudTrax"""
        self.users = []

        parameters = {'network': self.network['name']}
    
        logging.info('Requesting user statistics') 

        request = self.session.get(self.url['user'], params=parameters)

        logging.info('Received user statistics ok') 


        if request.status_code == 200:
            for raw_values in distill_html(request.content, 'table',
                                           {'class': 'inline sortable'}):
                self.users.append(User(raw_values))

        else:
            logging.error('Request failed') 
            exit(request.status_code)

        return self.users

    def report_nodes(self):
        """Return a string containing a pretty nodes report"""
        report = 'Node statistics for the last 24 hours\n'
        report += '-------------------------------------\n\n'

        self.get_nodes()

        report += 'Gateway nodes\n'
        report += draw_table('gateway', self.nodes)
        report += '\n\n'
        report += 'Relay nodes\n'
        report += draw_table('relay', self.nodes)
        report += '\n\n'
        report += 'Spare nodes\n'
        report += draw_table('spare', self.nodes)
        report += '\n\n'

        return report

    def report_users(self):
        """Return a string containing a pretty user report"""
        report = 'User statistics for the last 24 hours\n'
        report += '-------------------------------------\n\n'
        report += 'Users\n'

        table = texttable.Texttable()
        table.header(['Name\n(mac)',
                      'Last seen on',
                      'Blocked',
                      'MB Down',
                      'MB Up'])

        self.get_users()

        for user in self.users:
            table.add_row(user.get_table_row())

        report += table.draw()
        report += '\n\n'

        return report