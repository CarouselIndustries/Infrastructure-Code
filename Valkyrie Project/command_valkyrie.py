#!/usr/bin/env python
# https://github.com/jonviveiros/Infrastructure-Code
# https://github.com/CarouselIndustries/Infrastructure-Code

# DESCRIPTION
# The goal is to pull output from various SSH devices. Threading and device autodetection
# is leveraged to gather relevant information.
# Authentication via prompt
# TODO Handle enable account for Cisco devices.


import os
import json
import requests
import signal
import sys
import threading
from datetime import datetime
from queue import Queue

from netmiko import Netmiko, NetMikoTimeoutException, NetMikoAuthenticationException
from netmiko import SSHDetect

# These capture errors relating to hitting ctrl+C
signal.signal(signal.SIGINT, signal.SIG_DFL)  # KeyboardInterrupt: Ctrl-C

# TODO Change password method to getpass()
# Get username/password
username = input('Enter the username: ')
password = input('Enter the password: ')
secret = None


# Switch IP addresses from text file that has one IP per line
ip_addrs_file = open('ips.txt', encoding='UTF-8')
ip_addrs = ip_addrs_file.read().splitlines()

# List of commands to run split by line
commands_file = open('commands.txt', encoding='UTF-8')
commands = commands_file.read().splitlines()

commands_nexus_file = open('commands_nexus.txt', encoding='UTF-8')
commands_nexus = commands_nexus_file.read().splitlines()

# TODO Move this section such that folder creation does not occur if script fails
# Define the output folder
os.makedirs('valkyrie output', exist_ok=True)

# Set up thread count for number of threads to spin up.
num_threads = 5
# This sets up the queue
enclosure_queue = Queue()
# Set up thread lock so that only one thread prints at a time
print_lock = threading.Lock()

print('*****\nInitiating Valkyrie process...\n*****')

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
        print('Thread {}/{}: Acquired IP: {}'.format(i+1, num_threads, ip))

        # device_dict is copied over to net_connect
        device_dict = {
            'host': ip,
            'username': username,
            'password': password,
            'secret': secret,
            'device_type': 'autodetect'
        }

        # device type autodetect based on netmiko
        auto_device_dict = SSHDetect(**device_dict)
        device_os = auto_device_dict.autodetect()
        # print(device_os)
        # print(auto_device_dict.potential_matches)

        # Update device_dict device_type from 'autodetect' to the detected OS
        if device_os == None:
            print( 'Thread {}/{}: '.format(i+1, num_threads) + device_dict['host'] \
                   + ' returned device_type of: ' + device_dict['device_type'] + '\n')
            device_dict['device_type'] = 'autodetect'
        else:
            device_dict['device_type'] = device_os

        # Connect to the device, and print out auth or timeout errors
        try:
            net_connect = Netmiko(**device_dict)
            print('Connecting to: ' + net_connect.host + ' (' + device_dict['device_type'] + ')')

        except NetMikoTimeoutException:
            with print_lock:
                print('\n{}: ERROR: Connection to {} timed-out. \n'.format(i, ip))
            q.task_done()
            continue
        except NetMikoAuthenticationException:
            with print_lock:
                print('\n{}: ERROR: Authentication failed for {}. Stopping thread. \n'.format(i, ip))
            q.task_done()
            # Closing the process via os.kill - UNIX only?
            # os.kill(os.getpid(), signal.SIGUSR1)

        # Capture the output
        # TODO TextFSM to parse data

        # create two variables - one of hostname and the prompt level and another with just the hostname
        find_hostname = net_connect.find_prompt()
        hostname = find_hostname.rstrip('#>')
        print('Associated IP: ' + ip + '; Hostname: ' + hostname)

        # TODO Write file to a optional, specified folder
        # with print_lock:
        timenow = '{:%Y-%m-%d %H_%M_%S}'.format(datetime.now())
        filename = (hostname + ' ' + ip + ' - valkyrie output {0}.txt')
        serial_outputfile = open('valkyrie output/' + filename.format(timenow), 'w')
        print('Writing file name ' + hostname + ' ' + ip + ' - valkyrie output ' + format(timenow) + '.txt')

        if device_os == 'cisco_ios':
            for cmd in commands:
                # TODO Ignore blank lines or lines starting with '!'; print the comment but not instantiate NetMiko
                output = net_connect.send_command(cmd.strip(), delay_factor=1, max_loops=50)
                outfile_file(serial_outputfile, find_hostname, cmd, output)
        elif device_os == 'cisco_nxos':
            for cmd in commands_nexus:
                # TODO Ignore blank lines or lines starting with '!'; print the comment but not instantiate NetMiko
                output = net_connect.send_command(cmd.strip(), delay_factor=1, max_loops=50)
                outfile_file(serial_outputfile, find_hostname, cmd, output)
        else:
            cmd = 'show tech'
            output = net_connect.send_command(cmd.strip(), delay_factor=1, max_loops=50)
            outfile_file(serial_outputfile, find_hostname, cmd, output)
            print('Device returned no valid device_type - ran "show tech"')

        for cmd in commands:
        # TODO Ignore blank lines or lines starting with '!'; print the comment but not instantiate NetMiko
            output = net_connect.send_command(cmd.strip(), delay_factor=1, max_loops=50)
            # Write output to file
            outfile_file(serial_outputfile, find_hostname, cmd, output)
            #serial_outputfile.write((find_hostname + '\n') * 3)
            #serial_outputfile.write(find_hostname + cmd + '\n')
            #serial_outputfile.write(output + '\n')

        # Disconnect from device
        net_connect.disconnect()

        # Close the file
        serial_outputfile.close()

        # Set the queue task as complete, thereby removing it from the queue indefinitely
        print("Thread {}/{}: Completed".format(i+1, num_threads))
        q.task_done()

def outfile_file(serial_outputfile, find_hostname, cmd, output):
    # Takes in variables (serial_outputfile, find_hostname, cmd, output)
    # Writes output to file
    serial_outputfile.write((find_hostname + '\n') * 3)
    serial_outputfile.write(find_hostname + cmd + '\n')
    serial_outputfile.write(output + '\n')

def main():
    # Setting up threads based on number set above
    for i in range(num_threads):
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
    # serial_outputfile.close()
    print("*****\nCompleting Valkyrie process...\n*****")
    print(cn_joke['value'])

if __name__ == '__main__':
    try:
        main()
    except ValueError:
        print('No Valhalla for you')
        sys.exit()
