#!/bin/bash

ssh -i keys/user_ad_server_ssh_key debian@$(cat ip_address.txt)
