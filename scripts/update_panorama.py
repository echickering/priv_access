import requests
import xml.etree.ElementTree as ET
import urllib3
import logging  # Import the logging module

class UpdatePanorama:
    def __init__(self, token, base_url, state_data):
        self.token = token
        self.base_url = base_url
        self.state_data = state_data

    def get_devices(self,logger):
        headers = {'X-PAN-KEY': self.token}
        payload = {'type': 'op', 'cmd': '<show><devices><all/></devices></show>'}
        response = requests.post(self.base_url, headers=headers, params=payload, verify=False)
        logger.debug(f"Response from Panorama:\n{response.text}")
        root = ET.fromstring(response.content)
        return root.findall('.//result/devices/entry')

    def update_panorama_variables(self):
        # Get the logger
        logger = logging.getLogger()

        devices = self.get_devices(logger)
        for device in devices:
            serial = device.find('serial').text
            hostname = device.find('hostname').text

            logger.debug(f"Processing device {hostname} with serial {serial}")

            # Find matching VM in state data
            for region, instances in self.state_data.items():
                for instance_id, instance_details in instances.items():
                    if instance_details['vm_name'] == hostname:
                        logger.info(f"Found matching VM: {hostname}")

                        trust_ip = None
                        untrust_ip = None
                        trust_nexthop = None
                        untrust_nexthop = None
                        public_untrust_ip = None
                        ni = None  # Initialize ni here

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

                        logger.debug(f"Updating variables for VM: {hostname}")

                        # Update template variables in Panorama
                        self.update_variable(serial, '$trust_ip', trust_ip, logger)
                        self.update_variable(serial, '$untrust_ip', untrust_ip, logger)
                        self.update_variable(serial, '$trust_nexthop', trust_nexthop, logger)
                        self.update_variable(serial, '$untrust_nexthop', untrust_nexthop, logger)
                        self.update_variable(serial, '$public_untrust_ip', public_untrust_ip, logger)

                        logger.info(f"Variables updated for VM: {hostname}")
                        break

    def update_variable(self, serial, variable_name, value, logger):
        # Corrected XPath
        xpath = f"/config/devices/entry[@name='localhost.localdomain']/template-stack/entry[@name='PPA-TPL-Stack']/devices/entry[@name='{serial}']/variable/entry[@name='{variable_name}']/type"

        # XML element
        element = f"<ip-netmask>{value}</ip-netmask>"

        # Payload as per Palo Alto API standards
        payload = {
            'type': 'config',
            'action': 'set',
            'key': self.token,
            'xpath': xpath,
            'element': element
        }

        # Log the request content
        logger.debug(f"Request to Panorama: {payload}")

        # Make the request and log the response
        response = requests.post(self.base_url, params=payload, verify=False)
        logger.debug(f"Response from Panorama:\n{response.text}")

    def update_panorama(self):
        # Disable SSL warnings
        urllib3.disable_warnings()
        
        # Call methods to update Panorama variables
        self.update_panorama_variables()
