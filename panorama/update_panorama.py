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
        devices_list = []
        try:
            headers = {'X-PAN-KEY': self.token}
            payload = {'type': 'op', 'cmd': '<show><devices><all/></devices></show>'}
            logger.info(f"Request to Panorama: {headers}{payload}")
            response = requests.post(self.base_url, headers=headers, params=payload, verify=False)
            logger.info(f"Response from Panorama:\n{response.text}")
            root = ET.fromstring(response.content)
            devices = root.findall('.//result/devices/entry')
            for device in devices:
                serial = device.find('serial').text
                mgmt_ip = device.find('ip-address').text  # Adjusted to match your XML structure
                devices_list.append({'serial': serial, 'ipv4': mgmt_ip})

            if devices_list:
                logger.info("Devices successfully retrieved from Panorama.")
            else:
                logger.info("No devices found.")
            return devices_list
        except Exception as e:
            logger.error(f"Error while trying to get devices: {e}")
            return []

    def update_panorama_variables(self, logger, max_retries=150, delay=15):
        for attempt in range(max_retries):
            devices = self.get_devices(logger)  # Fetch devices from Panorama

            if not devices:
                logger.info(f'Waiting for devices to be registered. Retrying in {delay} seconds...Attempt: {attempt + 1} of Max Attempts: {max_retries}')
                time.sleep(delay)
                continue

            for device in devices:
                serial = device['serial']
                mgmt_ip = device['ipv4']

                # Find matching details in state_data based on mgmt_ip
                matched_details = next((details for region, details in self.state_data.items() if details['mgmt_ip'] == mgmt_ip), None)

                if matched_details:
                    logger.info(f"Processing device with serial {serial} and management IP {mgmt_ip}")
                    # Update Panorama variables for the matched device
                    self.update_variable(serial, '$trust_ip', matched_details['trust_ip'], logger)
                    self.update_variable(serial, '$untrust_ip', matched_details['untrust_ip'], logger)
                    self.update_variable(serial, '$trust_nexthop', matched_details['trust_nexthop'], logger)
                    self.update_variable(serial, '$untrust_nexthop', matched_details['untrust_nexthop'], logger)
                    self.update_variable(serial, '$public_untrust_ip', matched_details['public_untrust_ip'], logger)

                    logger.info(f"Updated variables for device with serial {serial}.")
                else:
                    logger.warning(f"No match found for device with serial {serial} and management IP {mgmt_ip}")

            if devices:
                logger.info("Successfully updated variables for all matched devices.")
                break  # Exit after successfully processing all devices

        if attempt >= max_retries - 1:
            logger.error("Reached maximum retry attempts without successfully updating all devices.")

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

    def commit_all_to_template_stack(self, logger, delay=150):
        payload = {
            'type': 'commit',
            'action': 'all',
            'cmd': f'<commit-all><shared-policy><force-template-values>yes</force-template-values><device-group><entry name="{self.dg_name}"/></device-group></shared-policy></commit-all>',
            'key': self.token
        }
        time.sleep(delay)
        response = requests.post(self.base_url, params=payload, verify=False)
        logger.info(f"Response from commit-all operation:\n{response.text}")

        # Parse the response and extract the job ID
        root = ET.fromstring(response.content)
        job_id = root.find('.//result/job').text if root.find('.//result/job') is not None else None
        return job_id

    def check_commit_status(self, job_id, logger, max_retries=30, delay=10):
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
                job_result = root.find('.//result/job/result').text if root.find('.//result/job/result') is not None else None
                if job_result == 'FAIL':
                    devices = root.findall('.//result/job/devices/entry')
                    not_connected_devices = [device for device in devices if device.find('status').text == 'not connected']
                    if not_connected_devices:
                        logger.warning("Some devices not connected. Retrying...")
                        commit_all_job_id = self.commit_all_to_template_stack(logger)
                        if commit_all_job_id:
                            job_id = commit_all_job_id  # Update job_id with the new one
                            time.sleep(delay)
                            continue
                    else:
                        logger.error("Commit failed for other reasons.")
                        return False
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

    def update_panorama(self):
        # Disable SSL warnings
        urllib3.disable_warnings()
        
        # Get the logger
        logger = logging.getLogger()

        # Call methods to update Panorama variables
        self.update_panorama_variables(logger)

        # Committing changes to Panorama
        job_id = self.commit_panorama(logger)
        if job_id and self.check_commit_status(job_id, logger):
            logger.info("Proceeding with commit-all to template stack.")
            commit_all_job_id = self.commit_all_to_template_stack(logger)
            if commit_all_job_id:
                self.check_commit_status(commit_all_job_id, logger)
