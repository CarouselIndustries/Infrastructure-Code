#!/usr/bin/env python3
# https://github.com/jonviveiros/Infrastructure-Code
# https://github.com/CarouselIndustries/Infrastructure-Code

# DESCRIPTION
# The goal is to pull output from various SSH devices. Threading and device autodetection
# are leveraged to gather relevant information. Device_type is recognized for supported
# devices to ensure only relevant commands are used.
# Authentication via prompt
# TODO Handle enable account for Cisco devices.

import re
import os
import json
import requests
import signal
import sys
import threading
from time import sleep
from getpass import getpass
from datetime import datetime, date
from queue import Queue
from paramiko.ssh_exception import NoValidConnectionsError, AuthenticationException

from netmiko import Netmiko, NetMikoTimeoutException, NetMikoAuthenticationException
from netmiko import SSHDetect

version = 0.49

# These capture errors relating to hitting ctrl+C
signal.signal(signal.SIGINT, signal.SIG_DFL)  # KeyboardInterrupt: Ctrl-C

# Get username/password
username = input('Enter the username: ')
password = getpass('Enter the password: ')
secret = None
ip_addrs = []

# Switch IP addresses from text file that has one IP per line
# ip_addrs_file = open('ips.txt', encoding='UTF-8')
# ip_addrs = ip_addrs_file.read().splitlines()

ipfile = input('Enter the IP Addresses filename or press [Enter] to use the default of ips.txt: ')

# TODO: Perform a check to ensure the file exists

if ipfile is '':
    with open('ips.txt', encoding='UTF-8') as ip_addrs_file:
        for line in ip_addrs_file:
            if re.match(r'\d', line[0]):
                ip_addrs.append(line.strip())
            else:
                continue
else:
    with open(ipfile, encoding='UTF-8') as ip_addrs_file:
        for line in ip_addrs_file:
            if re.match(r'\d', line[0]):
                ip_addrs.append(line.strip())
            else:
                continue


# List of commands to run split by line
commands_file = open('commands_cisco_ios.txt', encoding='UTF-8')
commands = commands_file.read().splitlines()

commands_nexus_file = open('commands_cisco_nexus.txt', encoding='UTF-8')
commands_nexus = commands_nexus_file.read().splitlines()

commands_wlc_file = open('commands_cisco_wlc.txt', encoding='UTF-8')
commands_wlc = commands_wlc_file.read().splitlines()

commands_asa_file = open('commands_cisco_asa.txt', encoding='UTF-8')
commands_asa = commands_asa_file.read().splitlines()

commands_showtech_file = open('commands_showtech.txt', encoding='UTF-8')
commands_showtech = commands_showtech_file.read().splitlines()

# Define the output folder
os.makedirs('valkyrie output', exist_ok=True)

# Set up thread count for number of threads to spin up.
threads = 5
# This sets up the queue
enclosure_queue = Queue()
# Set up thread lock so that only one thread prints at a time
print_lock = threading.Lock()

print('*****\nInitiating Valkyrie process v{} ...\n*****'.format(version))

# Fun Chuck Norris Joke at completion
url = 'https://api.chucknorris.io/jokes/random'
cn_resp = requests.get(url=url, headers={'Content-Type': 'application/json'})
cn_joke = json.loads(cn_resp.text)


# Function used in threads to connect to devices, passing in the thread # and queue
def deviceconnector(i, q):
    # This while loop runs indefinitely and grabs IP addresses from the queue and processes them
    # Loop will be blocked and wait if "ip = q.get()" is empty
    while True:

        ip = q.get()
        with print_lock:
            print('Th{}/{}: Acquired IP:  {}'.format(i+1, threads, ip))

        #Create an error log file
        errorfile = open('valkyrie output/valkyrie errors ' + str(date.today()) + '.txt', 'a')

        # device_dict is copied over to net_connect
        device_dict = {
            'host': ip,
            'username': username,
            'password': password,
            'secret': secret,
            'device_type': 'autodetect',
            'banner_timeout': 60,
            'conn_timeout': 60
            # Gather session output logs - TESTING ONLY
            # ,
            # 'session_log': 'session_output.txt'
        }

        # device type autodetect based on netmiko
        try:
            auto_device_dict = SSHDetect(**device_dict)
            device_os = auto_device_dict.autodetect()
            # Validate device type returned (Testing only)
            # print('===== {} =====\n===== {} ====='.format(device_os, auto_device_dict.potential_matches))

            # Update device_dict device_type from 'autodetect' to the detected OS
            if device_os is None:
                print('Th{}/{}: {} returned unsupported device_type of {}\n'.format(i + 1, threads, device_dict['host'],
                      device_os))
                device_dict['device_type'] = 'autodetect'
            else:
                device_dict['device_type'] = device_os

            # Connect to the device, and print out auth or timeout errors
            net_connect = Netmiko(**device_dict)
            print('Th{}/{}: Connecting to: {} ({})'.format(i+1, threads, net_connect.host, net_connect.device_type))
        except NetMikoTimeoutException:
            with print_lock:
                print('Th{}/{}: ERROR: Connection to {} timed-out. \n'.format(i+1, threads, ip))
                errorfile.write('[{}] {} ERROR: Connection timed-out. \n'.format(datetime.now().strftime('%H:%M:%S'), ip))
            q.task_done()
        except (NetMikoAuthenticationException, AuthenticationException):
            with print_lock:
                print('Th{}/{}: ERROR: Authentication failed for {}. Stopping thread. \n'.format(i+1, threads, ip))
                errorfile.write('[{}] {} ERROR: Authentication failed. \n'.format(datetime.now().strftime('%H:%M:%S'), ip))
            q.task_done()
        except NoValidConnectionsError:
            with print_lock:
                print('Th{}/{}: ERROR: No Connections available for device {}. \n'.format(i+1, threads, ip))
                errorfile.write('[{}] {} ERROR: No Connections available. \n'.format(datetime.now().strftime('%H:%M:%S'), ip))
            q.task_done()

        # Capture the output
        # TODO TextFSM to parse data

        # create two variables - one of hostname and the prompt level and another with just the hostname
        prompt = net_connect.find_prompt()
        hostname = prompt.rstrip('#>')
        print('Th{}/{}: Associated IP: {} with hostname: {}'.format(i+1, threads, ip, hostname))

        # TODO Write file to a optional, specified folder

        timenow = '{:%Y-%m-%d %H_%M_%S}'.format(datetime.now())
        start = datetime.now()
        filename = (hostname + ' ' + ip + ' - valkyrie output {0}.txt')
        outputfile = open('valkyrie output/' + filename.format(timenow), 'w')

        print('Th{}/{}: Writing file name "{} {} - valkyrie output {}.txt"'.format(
            i+1, threads, hostname, ip, format(timenow)))

        if device_os == 'cisco_ios':
            for cmd in commands:
                try:
                    if re.match(r'\w', cmd):
                        output = net_connect.send_command(cmd.strip(), delay_factor=1, max_loops=1000)
                        write_file(outputfile, prompt, cmd, output)
                    else:
                        outputfile.write(prompt + cmd + '\n')
                except (NetMikoTimeoutException, EOFError, OSError) as e:
                    exception_logging(e, i, threads, ip, hostname, cmd, prompt, outputfile, errorfile)
                    net_connect = Netmiko(**device_dict)
                    sleep(5)
        elif device_os == 'cisco_nxos':
            for cmd in commands_nexus:
                try:
                    if re.match(r'\w', cmd):
                        output = net_connect.send_command(cmd.strip(), delay_factor=1, max_loops=1000)
                        write_file(outputfile, prompt, cmd, output)
                    else:
                        outputfile.write(prompt + cmd + '\n')
                except (NetMikoTimeoutException, EOFError, OSError) as e:
                    exception_logging(e, i, threads, ip, hostname, cmd, prompt, outputfile, errorfile)
                    net_connect = Netmiko(**device_dict)
                    sleep(5)
        elif device_os == 'cisco_wlc':
            for cmd in commands_wlc:
                try:
                    if re.match(r'\w', cmd):
                        if cmd == 'show run-config':
                            output = net_connect.send_command_timing(cmd.strip(), delay_factor=1, max_loops=1000)
                            if 'Press Enter to continue' in output:
                                output += net_connect.send_command_timing('\n')
                            write_file(outputfile, prompt, cmd, output)
                        else:
                            output = net_connect.send_command(cmd.strip(), delay_factor=1, max_loops=1000)
                            write_file(outputfile, prompt, cmd, output)
                    else:
                        outputfile.write(prompt + cmd + '\n')
                except (NetMikoTimeoutException, EOFError, OSError) as e:
                    exception_logging(e, i, threads, ip, hostname, cmd, prompt, outputfile, errorfile)
                    net_connect = Netmiko(**device_dict)
                    sleep(5)
        elif device_os == 'cisco_asa':
            for cmd in commands_asa:
                try:
                    if re.match(r'\w', cmd):
                        output = net_connect.send_command(cmd.strip(), delay_factor=1, max_loops=1000)
                        write_file(outputfile, prompt, cmd, output)
                    else:
                        outputfile.write(prompt + cmd + '\n')
                except (NetMikoTimeoutException, EOFError, OSError) as e:
                    exception_logging(e, i, threads, ip, hostname, cmd, prompt, outputfile, errorfile)
                    net_connect = Netmiko(**device_dict)
                    sleep(5)
        else:
            for cmd in commands_showtech:
                try:
                    if re.match(r'\w', cmd):
                        output = net_connect.send_command(cmd.strip(), delay_factor=1, max_loops=1000)
                        write_file(outputfile, prompt, cmd, output)
                    else:
                        outputfile.write(prompt + cmd + '\n')
                except (NetMikoTimeoutException, EOFError, OSError) as e:
                    exception_logging(e, i, threads, ip, hostname, cmd, prompt, outputfile, errorfile)
                    net_connect = Netmiko(**device_dict)
                    sleep(5)
        # Disconnect from device
        net_connect.disconnect()

        # Close the file
        outputfile.close()
        # errorfile.write('Closing file...')
        errorfile.close()

        # verify elapsed time per device
        end = datetime.now()
        print('Th{}/{}: Completed. Time elapsed: {}'.format(i+1, threads, (end-start)))

        # Set the queue task as complete, thereby removing it from the queue indefinitely
        q.task_done()


def exception_logging(e, i, threads, ip, hostname, cmd, prompt, outputfile, errorfile):
    print('Th{}/{}: Exception occurred: {}'.format(i + 1, threads, repr(e)))
    print('Th{}/{}: ERROR: Connection lost. Reconnecting to: {} ({})\n'.format(i + 1, threads, ip, hostname))
    outputfile.write('{} {} !!!!!Command failed - run manually!!!!!\n'.format(prompt, cmd))
    errorfile.write('[{}] {} ({}) failed to run command: {}\n'.format(
        datetime.now().strftime('%H:%M:%S'), ip, hostname, cmd))


def write_file(outputfile, prompt, cmd, output):
    # Takes in variables (outputfile, prompt, cmd, output) and writes output to file
    outputfile.write((prompt + '\n') * 3)
    outputfile.write(prompt + cmd + '\n')
    outputfile.write(output + '\n')


def main():
    # Setting up threads based on number set above
    for i in range(threads):
        # Create the thread using 'deviceconnector' as the function, passing in
        # the thread number and queue object as parameters
        thread = threading.Thread(target=deviceconnector, args=(i, enclosure_queue))
        # Set the thread as a background daemon/job
        thread.setDaemon(True)
        # Start the thread
        thread.start()

    # For each ip address in "ip_addrs", add that IP address to the queue
    for ip_addr in ip_addrs:
        enclosure_queue.put(ip_addr)

    # Wait for all tasks in the queue to be marked as completed (task_done)
    enclosure_queue.join()
    # outputfile.close()
    print("*****\nCompleting Valkyrie process ...\n*****")
    # print(cn_joke['value'])


if __name__ == '__main__':
    try:
        main()
    except ValueError:
        print('No Valhalla for you')
        sys.exit()
