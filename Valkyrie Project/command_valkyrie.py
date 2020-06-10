#!/usr/bin/env python
# https://github.com/jonviveiros/<TBD>

# DESCRIPTION
# The goal is to pull output from various SSH devices. Ideally threading and device autodetection is leveraged to gather
# relevant information. Authentication via prompt
# TODO Handle enable account for Cisco devices.


# from netmiko import SSHDetect
import os
import signal
import sys
import threading
from datetime import datetime
from queue import Queue

from netmiko import Netmiko, NetMikoTimeoutException, NetMikoAuthenticationException

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


# Function used in threads to connect to devices, passing in the thread # and queue
def deviceconnector(i, q):
    # This while loop runs indefinitely and grabs IP addresses from the queue and processes them
    # Loop will be blocked and wait if "ip = q.get()" is empty
    while True:

        ip = q.get()
        print("Thread {}/{}: Acquired IP: {}".format(i+1, num_threads, ip))

        # device_dict is copied over to net_connect
        device_dict = {
            'host': ip,
            'username': username,
            'password': password,
            'secret': secret,
            'device_type': 'cisco_ios'
        }

        # Connect to the device, and print out auth or timeout errors
        try:
            net_connect = Netmiko(**device_dict)
            print('Connecting to ' + net_connect.host)

        except NetMikoTimeoutException:
            with print_lock:
                print("\n{}: ERROR: Connection to {} timed-out.\n".format(i, ip))
            q.task_done()
            continue
        except NetMikoAuthenticationException:
            with print_lock:
                print('\n{}: ERROR: Authentication failed for {}. Stopping thread. \n'.format(i, ip))
            q.task_done()
            # CLosing the process via os.kill - UNIX only?
            # os.kill(os.getpid(), signal.SIGUSR1)

        # Capture the output, and use TextFSM to parse data
        find_hostname = net_connect.find_prompt()
        # TODO Change translate to replace
        hostname = find_hostname.rstrip('#>')
        print('Associated IP: ' + ip + ' with the hostname of: ' + hostname)
        # echo_hostname = net_connect.find_prompt()
        # output2 = net_connect.send_command(command, use_textfsm=False)

        # TODO Write file to a optional, specified folder
        with print_lock:
            timenow = '{:%Y-%m-%d %H_%M_%S}'.format(datetime.now())
            filename = (hostname + ' ' + ip + ' - valkyrie output {0}.txt')
            serial_outputfile = open('valkyrie output/' + filename.format(timenow), 'w')
            print('Writing file name ' + hostname + ' ' + ip + ' - valkyrie output ' + format(timenow) + '.txt')

            for cmd in commands:
            # TODO Ignore line in commands with a comment '!' at the start; print the comment but not instantiate NetMiko
                output = net_connect.send_command(cmd.strip(), delay_factor=1, max_loops=50)
            # output = net_connect.send_config_set(commands)
            # Notify write output to file
                serial_outputfile.write((find_hostname + '\n') * 3)
                serial_outputfile.write(find_hostname + cmd + '\n')
                serial_outputfile.write(output + '\n')

        # Disconnect from device
        net_connect.disconnect()

        # Close the file
        serial_outputfile.close()

        # Set the queue task as complete, thereby removing it from the queue indefinitely
        q.task_done()


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


if __name__ == '__main__':
    try:
        main()
    except ValueError:
        print('No Valhalla for you')
        sys.exit()
