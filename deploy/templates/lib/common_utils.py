#!/usr/bin/env python3
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals
from requests import get

class internet(object):

    def __init__(self):
        self.public_ip_address = get('https://api.ipify.org').text


    def get_actual_ip(self):
        return self.public_ip_address
