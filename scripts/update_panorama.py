# project/scripts/update_panorama.py
import requests
import xml.etree.ElementTree as ET
import urllib3
import logging
import time
import json

class UpdatePanorama:
    def __init__(self, stack_name, dg_name, token, base_url, state_data):
        self.stack_name = stack_name
        self.dg_name = dg_name
        self.token = token
        self.base_url = base_url
        self.state_data = state_data

    def get_devices(self, logger):
        try:
            headers = {'X-PAN-KEY': self.token}
            payload = {'type': 'op', 'cmd': '<show><devices><all/></devices></show>'}
            logger.info(f"Request to Panorama: {headers}{payload}")
            response = requests.post(self.base_url, headers=headers, params=payload, verify=False)
            logger.info(f"Response from Panorama:\n{response.text}")
            root = ET.fromstring(response.content)
            devices = root.findall('.//result/devices/entry')

            if devices:
                logger.info("Devices successfully retrieved from Panorama.")
                return devices
            else:
                logger.info("No devices found.")
                return None
        except Exception as e:
            logger.error(f"Error while trying to get devices: {e}")
            return None

    def update_panorama_variables(self, max_retries=60, delay=30):
        # Get the logger
        logger = logging.getLogger()

        processed_devices = set()  # Track processed devices
        state_devices = {details['vm_name'] for region, instances in self.state_data.items() for _, details in instances.items()}  # Set of all VM names in state_data

        for attempt in range(max_retries):
            devices = self.get_devices(logger)
            if devices:
                for device in devices:
                    serial_elem = device.find('serial')
                    hostname_elem = device.find('hostname')

                    if serial_elem is None or hostname_elem is None:
                        logger.error("Serial or hostname element missing in device data. Skipping device.")
                        continue

                    serial = serial_elem.text
                    hostname = hostname_elem.text

                    if hostname not in state_devices or hostname in processed_devices:
                        continue  # Skip if device is not in state_data or already processed

                    logger.info(f"Processing device {hostname} with serial {serial}")

                    # Find matching VM in state data
                    for region, instances in self.state_data.items():
                        for instance_id, instance_details in instances.items():
                            if instance_details['vm_name'] == hostname:
                                instance_details['serial'] = serial
                                logger.info(f"Found matching VM: {hostname}")

                                trust_ip = None
                                untrust_ip = None
                                trust_nexthop = None
                                untrust_nexthop = None
                                public_untrust_ip = None
                                ni = None

                                # Find the correct Network Interface (ni) based on conditions
                                for ni_candidate in instance_details['NetworkInterfaces']:
                                    if ni_candidate['DeviceIndex'] == 2:
                                        trust_ip = ni_candidate['PrivateIpCidr']
                                        trust_nexthop = ni_candidate['DefaultGW']
                                    elif ni_candidate['DeviceIndex'] == 0:
                                        untrust_ip = ni_candidate['PrivateIpCidr']
                                        untrust_nexthop = ni_candidate['DefaultGW']
                                        ni = ni_candidate  # Assign ni here

                                # Find the correct ElasticIP (eip) based on conditions
                                for eip in instance_details['ElasticIPs']:
                                    if ni and eip['InterfaceId'] == ni['InterfaceId']:
                                        public_untrust_ip = eip['PublicIP']

                                logger.info(f"Updating variables for VM: {hostname}")

                                # Update template variables in Panorama
                                self.update_variable(serial, '$trust_ip', trust_ip, logger)
                                self.update_variable(serial, '$untrust_ip', untrust_ip, logger)
                                self.update_variable(serial, '$trust_nexthop', trust_nexthop, logger)
                                self.update_variable(serial, '$untrust_nexthop', untrust_nexthop, logger)
                                self.update_variable(serial, '$public_untrust_ip', public_untrust_ip, logger)

                                logger.info(f"Variables updated for VM: {hostname}")
                                processed_devices.add(hostname)  # Add hostname to processed_devices

            if processed_devices == state_devices:
                logger.info("All devices from state data have been processed.")
                break  # Exit if all devices in state_data are processed

            if attempt < max_retries - 1:
                logger.info(f"Waiting for more devices to register. Retrying in {delay} seconds\nAttempt: {attempt} of max attempt:{max_retries}...")
                time.sleep(delay)

        if processed_devices != state_devices:
            logger.error("Not all devices from state data were processed.")
            # Additional logic for unprocessed devices can be added here

    def update_variable(self, serial, variable_name, value, logger):
        # XPath
        xpath = f"/config/devices/entry[@name='localhost.localdomain']/template-stack/entry[@name='{self.stack_name}']/devices/entry[@name='{serial}']/variable/entry[@name='{variable_name}']/type"

        # XML element
        element = f"<ip-netmask>{value}</ip-netmask>"

        # Payload
        payload = {
            'type': 'config',
            'action': 'set',
            'key': self.token,
            'xpath': xpath,
            'element': element
        }

        # Log the request content
        logger.info(f"Request to Panorama: {payload}")

        # Make the request and log the response
        response = requests.post(self.base_url, params=payload, verify=False)
        logger.debug(f"Response from Panorama:\n{response.text}")
    
    def commit_panorama(self, logger):
        payload = {
            'type': 'commit',
            'cmd': '<commit></commit>',
            'key': self.token
        }
        response = requests.post(self.base_url, params=payload, verify=False)
        logger.info(f"Response from commit operation:\n{response.text}")
        
        # Parse the response and extract the job ID
        root = ET.fromstring(response.content)
        job_id = root.find('.//result/job').text if root.find('.//result/job') is not None else None
        return job_id

    def commit_all_to_template_stack(self, logger):
        payload = {
            'type': 'commit',
            'action': 'all',
            # 'cmd': f'<commit-all><template-stack><name>{self.stack_name}</name></template-stack></commit-all>',
            'cmd': f'<commit-all><shared-policy><force-template-values>yes</force-template-values><device-group><entry name="{self.dg_name}"/></device-group></shared-policy></commit-all>',
            'key': self.token
        }
        logger.info(f'Payload for commit_all: {payload}')
        response = requests.post(self.base_url, params=payload, verify=False)
        logger.info(f"Response from commit-all operation:\n{response.text}")

        # Parse the response and extract the job ID
        root = ET.fromstring(response.content)
        job_id = root.find('.//result/job').text if root.find('.//result/job') is not None else None
        return job_id

    def check_commit_status(self, job_id, logger, max_retries=20, delay=30):
        for attempt in range(max_retries):
            payload = {
                'type': 'op',
                'cmd': f'<show><jobs><id>{job_id}</id></jobs></show>',
                'key': self.token
            }
            response = requests.post(self.base_url, params=payload, verify=False)
            logger.info(f"Response from job status check:\n{response.text}")

            root = ET.fromstring(response.content)
            status = root.find('.//result/job/status').text if root.find('.//result/job/status') is not None else None

            if status == 'FIN':
                logger.info(f"Commit job {job_id} completed successfully.")
                return True
            elif status in ['ACT', 'PEND']:
                logger.info(f"Commit job {job_id} is still in progress. Waiting {delay} seconds before next check.")
                time.sleep(delay)
            else:
                logger.error(f"Commit job {job_id} failed or status is unknown.")
                return False

        logger.error(f"Maximum retries reached for commit job {job_id} status check.")
        return False


    def write_state_to_file(self, file_path='./state/state-ec2.json'):
        with open(file_path, 'w') as f:
            json.dump(self.state_data, f, indent=4)

    def update_panorama(self):
        # Disable SSL warnings
        urllib3.disable_warnings()
        
        # Get the logger
        logger = logging.getLogger()

        # Call methods to update Panorama variables
        self.update_panorama_variables()

        # Committing changes to Panorama
        job_id = self.commit_panorama(logger)
        if job_id and self.check_commit_status(job_id, logger):
            logger.info("Proceeding with commit-all to template stack.")
            commit_all_job_id = self.commit_all_to_template_stack(logger)
            if commit_all_job_id:
                self.check_commit_status(commit_all_job_id, logger)
