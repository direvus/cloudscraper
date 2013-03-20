#!/usr/bin/env python
""" cloudscraper.py

 A tool to extract and archive usage information from the CloudTrax wifi mesh
dashboard (cloudtrax.com).

"""

from BeautifulSoup import BeautifulSoup
from time import time
import argparse
import cStringIO
import requests
import texttable
import ConfigParser
import Image

CONFIG_FILE = 'cloudscraper.conf'

NODE_STATUS = {'gw_down': '1',
               'relay_down': '2',
               'gw_up': '3',
               'relay_up': '4',
               'spare_gw_down': '5',
               'spare_down': '6',
               'spare_gw_up': '7',
               'spare_up': '8'}

def underline(text):
    """Returns an underlined version of the text supplied"""

    return text + '\n' + (len(text) * '-') + '\n'

def print_if_verbose(message):
    """Print the message to stdout if verbose output is requested"""
    if args.verbose:
        print timer.get_elapsed_time(), message

def draw_table(entity_type, entities):
    """Draws a text table representation of the data supplied"""

    header = {'gateway': ['Name\n(Firmware)',
                          'Users',
                          'DL MB\nUL MB',
                          'Up\n(Down)',
                          'IP Address'],
              'relay': ['Name\n(Firmware)',
                        'Users',
                        'DL MB\nUL MB',
                        'Gateway',
                        'Up\n(Down)',
                        'Latency\n(Hops)'],
              'spare': ['Name\n(Firmware)',
                        'Users',
                        'DL MB\nUL MB',
                        'Up\n(Down)',
                        'IP Address'],
              'user': ['Name\n(mac)',
                       'Last seen on',
                       'Blocked',
                       'MB Down',
                       'MB Up']}

    table = texttable.Texttable()
    table.header(header[entity_type])

    for entity in entities:
        if entity.get_type() == entity_type:
            table.add_row(entity.get_table_row())


    return table.draw()

def distill_html(content, element, identifier):
    distilled_text = []
    
    """Accept some HTML and return the filtered output"""
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


class Timer:
    """Universal stopwatch class"""
    def __init__(self):
        # Start the clock
        self.start_time = time()

    def get_elapsed_time(self):
        """Returns the number of seconds elapsed"""
        return "%.2f" % (time() - self.start_time)

class Node:
    """CloudTrax node class"""

    def __init__(self, session, values, checkin_url):
        """Constructor"""
        # TODO: time_since_last_checkin can be a 2 element array if down or late.
        if values[0][0] == NODE_STATUS['gw_up']:
            self.node_type = 'gateway'
            self.node_status = 'up'
        elif values[0][0] == NODE_STATUS['gw_down']:
            self.node_type = 'gateway'
            self.node_status = 'down'
        elif values[0][0] == NODE_STATUS['relay_up']:
            self.node_type = 'relay'
            self.node_status = 'down'
        elif values[0][0] == NODE_STATUS['relay_down']:
            self.node_type = 'relay'
            self.node_status = 'down'
        elif values[0][0] == NODE_STATUS['spare_gw_up']:
            self.node_type = 'spare'
            self.node_status = 'up'
        elif values[0][0] == NODE_STATUS['spare_gw_down']:
            self.node_type = 'spare'
            self.node_status = 'down'
        elif values[0][0] == NODE_STATUS['spare_up']:
            self.node_type = 'spare'
            self.node_status = 'up'
        elif values[0][0] == NODE_STATUS['spare_down']:
            self.node_type = 'spare'
            self.node_status = 'down'
        self.name = values[1][0]
        self.comment = values[1][-1]
        self.mac = values[2][0]
        self.ip = values[2][1]
        self.chan_24 = values[3][0]
        self.chan_58 = values[3][1]
        self.users_24 = values[4][0]
        self.download_24 = values[5][0]
        self.upload_24 = values[5][1]
        self.uptime = values[6][0]
        self.fw_version = values[7][0]
        self.fw_name = values[7][1]
        self.load = values[8][0]
        self.memfree = values[8][1]
        self.time_since_checkin = values[9][0]
        self.gateway_name = values[10][0]
        self.gateway_ip = values[10][1]
        self.hops = values[11][0]
        self.latency = values[12][0]

        self.time_as_gw = 0
        self.time_as_relay = 0
        self.time_offline = 0

        self.checkin_url = checkin_url

        self.scrape_checkin_data(session)

    def get_mac(self):
        """Return the mac address of this node"""
        return self.mac

    def get_time_offline(self):
        """Return a float of the percent of time in 24hrs offline"""
        return self.time_offline

    def get_time_gw(self):
        """Return a float of the percent of time in 24hrs online as a gateway node"""
        return self.time_as_gw

    def get_time_relay(self):
        """Return a float of the percent of time in 24hrs online as a relay node"""
        return self.time_as_relay

    def get_type(self):
        """Return a string that describes the node type."""
        return self.node_type

    def get_table_row(self):
        """Returns a list of items that match up to the screen text table for the node type"""

        if self.node_type == 'gateway' or self.node_type == 'spare':
            row = [self.name + '\n(' + self.fw_version + ')',
                   self.users_24,
                   self.download_24 + '\n(' + self.upload_24 + ')',
                   str(self.time_as_gw) + '%\n(' + str(self.time_offline) + '%)',
                   self.gateway_ip]

        elif self.node_type == 'relay':
            row = [self.name + '\n(' + self.fw_version + ')',
                   self.users_24,
                   self.download_24 + '\n(' + self.upload_24 + ')',
                   self.gateway_name,
                   str(self.time_as_relay) + '%\n(' + str(self.time_offline) + '%)',
                   self.latency + 'ms\n(' + self.hops + ')']

        return row

    def scrape_checkin_data(self, session):
        """Scrape checkin information on the current node"""

        parameters = {'mac': self.mac,
                      'legend': '0'}

        print_if_verbose('Requesting node checkin status for ' + self.mac)

        request = session.get(self.checkin_url, params=parameters)

        self.colour_counter = {'cccccc': 0, '1faa5f': 0, '4fdd8f': 0}

        self.checkin_img = Image.open(cStringIO.StringIO(request.content))
        self.checkin_img_width = self.checkin_img.size[0]
        self.checkin_img_height = self.checkin_img.size[1]

        ROW = 1

        pixelmap = self.checkin_img.load()

        for col in range(0, self.checkin_img_width):
            pixel_colour = str("%x%x%x" % (pixelmap[col, ROW][0], pixelmap[col, ROW][1], pixelmap[col, ROW][2]))

            if pixel_colour in self.colour_counter.keys() and pixel_colour != '000':
                self.colour_counter[pixel_colour] += 1
            else:
                self.colour_counter[pixel_colour] = 1


        # Convert number of pixels into a percent
        self.time_as_gw = self.colour_counter['1faa5f'] / (self.checkin_img_width - 2) * 100
        self.time_as_relay = self.colour_counter['4fdd8f'] / (self.checkin_img_width - 2) * 100
        self.time_offline = self.colour_counter['cccccc'] / (self.checkin_img_width - 2) * 100

        return self.colour_counter


class User:
    """Wifi user class"""

    def __init__(self, values):
        """Constructor"""
        self.values = {'name': values[0][0],
                       'mac': values[0][-1],
                       'node_name': values[1][0],
                       'node_mac': values[1][1],
                       'rssi': values[3][0],
                       'rate': values[4][0],
                       'MCS': values[4][1],
                       'kb_down': values[5][0].replace(',', ''),
                       'kb_up': values[6][0].replace(',', ''),
                       'blocked': values[8][0]}
                       #'device_vendor': values[2]}

        print_if_verbose('Creating user object for ' + self.values['mac'])

    def get_type(self):
        """Return a string that describes the object type."""
        return 'user'

    def get_values(self):
        """Returns a bunch of values"""
        return self.values

    def get_table_row(self):
        """Returns a list of items to include in the user screen text table"""

        row = [self.values['name'] + '\n(' + self.values['mac'] + ')',
               self.values['node_name'] + '\n(' + self.values['node_mac'] + ')',
               self.values['blocked'],
               str(self.get_dl_usage()),
               str(self.get_ul_usage())]

        return row

    def get_dl_usage(self):
        """Returns an float with the number of MB downloaded in the past 24hrs"""
        return '%.2f' % (float(self.values['kb_down']) / 1000)

    def get_ul_usage(self):
        """Returns an float with the number of MB uploaded in the past 24hrs"""
        return '%.2f' % (float(self.values['kb_up']) / 1000)


class CloudTrax:
    """CloudTrax connector class"""

    def __init__(self, network, verbose):
        """Constructor"""
        self.network = network
        self.nodes = []
        self.users = []

        self.verbose = verbose
        print_if_verbose('Verbose output is turned on')

        self.config = ConfigParser.RawConfigParser()
        self.config.read(CONFIG_FILE)

        self.cloudtrax_url = self.config.get('common', 'cloudtrax_url')
        self.login_url = self.cloudtrax_url + self.config.get('common', 'login_page')
        self.data_url = self.cloudtrax_url + self.config.get('common', 'data_page')
        self.user_url = self.cloudtrax_url + self.config.get('common', 'user_page')
        self.checkin_url = self.cloudtrax_url + self.config.get('common', 'node_checkin_page')

        self.username = self.config.get(self.network, 'username')
        self.password = self.config.get(self.network, 'password')

    def login(self):
        """Method to login and create a web session"""
        self.session = requests.session()

        print_if_verbose('Logging in to CloudTrax Dashboard')

        parameters = {'account': self.username,
                      'password': self.password,
                      'status': 'View Status'}

        try:
            s = self.session.post(self.login_url, data=parameters)
            s.raise_for_status()

        except requests.exceptions.HTTPError:
            print_if_verbose('There was a HTTP error')
            exit(1)
        except requests.exceptions.ConnectionError:
            print_if_verbose('There was a connection error')
            exit(1)

        return self.session

    def get_session(self):
        """Return session id"""
        return self.session

    def get_request(self):
        """Return request id"""
        return self.request

    def get_nodes(self):
        """Return a list of nodes"""

        # Refresh the network status if the nodes list is empty
        if len(self.nodes) == 0:
            print_if_verbose('Refreshing node status from CloudTrax')
            self.refresh_network_status()

        return self.nodes

    def get_users(self):
        """Return network status"""
        if len(self.users) == 0:
            print_if_verbose('Refreshing user statistics from CloudTrax')
            self.refresh_users()

        return self.users

    def refresh_network_status(self):
        """Return network information scraped from CloudTrax"""
        self.nodes = []

        parameters = {'network': self.network,
                      'showall': '1',
                      'details': '1'}
    
        print_if_verbose('Requesting network status') 

        self.request = self.session.get(self.data_url, params=parameters)

        print_if_verbose('Received network status ok') 

        if self.request.status_code == 200:
            for raw_values in distill_html(self.request.content, 'table', {'id': 'mytable'}):
                self.nodes.append(Node(self.session, raw_values, self.checkin_url))

        else:
            print_if_verbose('Request failed') 
            exit(self.request.status_code)

        return self.nodes

    def refresh_users(self):
        """Return a list of wifi user statistics scraped from CloudTrax"""
        self.users = []

        parameters = {'network': self.network}
    
        print_if_verbose('Requesting user statistics') 

        self.request = self.session.get(self.user_url, params=parameters)

        print_if_verbose('Received user statistics ok') 


        if self.request.status_code == 200:
            for raw_values in distill_html(self.request.content, 'table', {'class': 'inline sortable'}):
                self.users.append(User(raw_values))

        else:
            print_if_verbose('Request failed') 
            exit(self.request.status_code)

        return self.users


#
# Program starts here!
#

parser = argparse.ArgumentParser(description='Statistics scraper for the CloudTrax controller')
parser.add_argument('-n', '--network', nargs=1, 
                    help='The wifi network name on CloudTrax')
parser.add_argument('-f', '--file', nargs=1, 
                    help='Store the output to a file')
parser.add_argument('-d', '--database', nargs=1, 
                    help='Store the output to a database')
parser.add_argument('-s', '--screen', action='store_true', default=False, 
                    help='Display the output to stdout')
parser.add_argument('-v', '--verbose', action='store_true', default=False, 
                    help='Be Verbose')
parser.add_argument('-N', '--network-status', help='Get the network status')
parser.add_argument('-U', '--usage-stats', help='Get the usage statistics')
args = parser.parse_args()

if args.verbose:
    timer = Timer()

if args.network:
    cloudtrax = CloudTrax(args.network[0], args.verbose)
    cloudtrax.login()

    if args.screen:
        cloudtrax.get_nodes()
        cloudtrax.get_users()
        underline('Usage for the last 24 hours')
        print '\n' + 'Gateway nodes'
        print draw_table('gateway', cloudtrax.get_nodes())
        print '\n' + 'Relay nodes'
        print draw_table('relay', cloudtrax.get_nodes())
        print '\n' + 'Spare nodes'
        print draw_table('spare', cloudtrax.get_nodes())
        print '\n' + 'Users'
        print draw_table('user', cloudtrax.get_users())

else:
    parser.print_help()
    exit(1)

