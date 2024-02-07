# project/scripts/update_panorama.py
import requests
import xml.etree.ElementTree as ET
import urllib3
import logging
import time
import json

class UpdatePanorama:
    def __init__(self, config, template, stack_name, dg_name, token, base_url, state_data):
        self.config = config
        self.template = template
        self.stack_name = stack_name
        self.dg_name = dg_name
        self.token = token
        self.base_url = base_url
        self.state_data = state_data

    def set_base_variable(self, logger):
        # Set all variables to template based on the first instance, eventually each device will be overwritten.
        first_instance_data = next(iter(self.state_data.values()))
        for key, value in first_instance_data.items():
            variable_name = key
            xpath = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/variable/entry[@name='${variable_name}']/type"
            element = f"<ip-netmask>{value}</ip-netmask>"
            payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
            logger.debug(f"Request to Panorama: {payload}")
            response = requests.post(self.base_url, params=payload, verify=False)
            #
            root = ET.fromstring(response.content)
            status = root.find('.//msg').text
            if status == "command succeeded":
                logger.info(f"Variable {variable_name} set {status}")
            else:
                logger.error(f"Response from Panorama:\n{response.text}")

    def set_ipsec_crypto_profile(self, logger):
        # Set all variables to template based on the first instance, eventually each device will be overwritten.
        prof_name = self.config['vpn']['crypto_settings']['ipsec_crypto']['name']
        ipsec_prof_name = f'{self.template}_{prof_name}'
        auth = self.config['vpn']['crypto_settings']['ipsec_crypto']['auth']
        dh_group = self.config['vpn']['crypto_settings']['ipsec_crypto']['dh_group']
        encryption = self.config['vpn']['crypto_settings']['ipsec_crypto']['encryption']
        xpath = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/config/devices/entry[@name='localhost.localdomain']/network/ike/crypto-profiles/ipsec-crypto-profiles/entry[@name='{ipsec_prof_name}']"
        element = f"""
            <esp>
                <authentication>
                    <member>{auth}</member>
                </authentication>
                <encryption>
                    <member>{encryption}</member>
                </encryption>
            </esp>
            <lifetime>
                <hours>1</hours>
            </lifetime>
            <dh-group>{dh_group}</dh-group>"""
        payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
        logger.debug(f"Request to Panorama: {payload}")
        response = requests.post(self.base_url, params=payload, verify=False)
        #
        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        if status == "command succeeded":
            logger.info(f"Ipsec Profile {ipsec_prof_name} set {status}")
            self.set_ike_crypto_profile(logger, ipsec_prof_name)
        else:
            logger.error(f"Response from Panorama:\n{response.text}")


    def set_ike_crypto_profile(self, logger, ipsec_prof_name):
        # Set all variables to template based on the first instance, eventually each device will be overwritten.
        prof_name = self.config['vpn']['crypto_settings']['ike_crypto']['name']
        ike_prof_name = f'{self.template}_{prof_name}'
        auth = self.config['vpn']['crypto_settings']['ike_crypto']['auth']
        dh_group = self.config['vpn']['crypto_settings']['ike_crypto']['dh_group']
        encryption = self.config['vpn']['crypto_settings']['ike_crypto']['encryption']
        xpath = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/config/devices/entry[@name='localhost.localdomain']/network/ike/crypto-profiles/ike-crypto-profiles/entry[@name='{ike_prof_name}']"
        element = f"""<hash>
                <member>{auth}</member>
              </hash>
              <dh-group>
                <member>{dh_group}</member>
              </dh-group>
              <encryption>
                <member>{encryption}</member>
              </encryption>
              <lifetime>
                <hours>8</hours>
              </lifetime>"""
        payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
        logger.debug(f"Request to Panorama: {payload}")
        response = requests.post(self.base_url, params=payload, verify=False)
        #
        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        if status == "command succeeded":
            logger.info(f"Ike Profile {ike_prof_name} set {status}")
            self.set_ike_gateway(logger, ike_prof_name, ipsec_prof_name)
        else:
            logger.error(f"Response from Panorama:\n{response.text}")

    def set_ike_gateway(self, logger, ike_prof_name, ipsec_prof_name):
        # Set all variables to template based on the first instance, eventually each device will be overwritten.
        count = 7499
        first_instance_data = next(iter(self.state_data.values()))
        for site, value in first_instance_data.items():
            if site.startswith('site'):
                suffix = site
                template = self.template
                prof_name = f'{template}-IKE_GW'
                ike_gw_name = f'{prof_name}_{suffix}'
                psk = self.config['vpn']['crypto_settings']['ike_gw']['psk']
                xpath = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/config/devices/entry[@name='localhost.localdomain']/network/ike/gateway/entry[@name='{ike_gw_name}']"
                element = f"""
                    <authentication>
                        <pre-shared-key>
                            <key>{psk}</key>
                        </pre-shared-key>
                    </authentication>
                    <protocol>
                        <ikev2>
                            <dpd>
                                <enable>yes</enable>
                            </dpd>
                            <ike-crypto-profile>{ike_prof_name}</ike-crypto-profile>
                        </ikev2>
                        <version>ikev2</version>
                    </protocol>
                    <local-address>
                        <interface>ethernet1/1</interface>
                    </local-address>
                    <protocol-common>
                        <nat-traversal>
                        <enable>yes</enable>
                        </nat-traversal>
                        <fragmentation>
                        <enable>no</enable>
                        </fragmentation>
                    </protocol-common>
                    <peer-address>
                        <ip>${suffix}</ip>
                    </peer-address>
                    <local-id>
                        <id>$untrust_ip_base</id>
                        <type>ipaddr</type>
                    </local-id>"""
                payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
                logger.debug(f"Request to Panorama: {payload}")
                response = requests.post(self.base_url, params=payload, verify=False)
                #
                root = ET.fromstring(response.content)
                status = root.find('.//msg').text
                if status == "command succeeded":
                    logger.info(f"Ike Gateway {ike_gw_name} set {status}")
                    count += 1
                    self.set_tunnel_interface(logger, count, ike_gw_name, ipsec_prof_name)
                else:
                    logger.error(f"Response from Panorama:\n{response.text}")
                    return

    def set_tunnel_interface(self, logger, count, ike_gw_name, ipsec_prof_name):
        vr_name = self.config['palo_alto']['panorama']['VirtualRouter']

        xpath = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/config/devices/entry[@name='localhost.localdomain']/network/interface/tunnel/units"
        element = f"<entry name='tunnel.{count}'/>"
        payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
        logger.debug(f"Request to Panorama: {payload}")
        response = requests.post(self.base_url, params=payload, verify=False)

        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        if "command succeeded" in status:
            logger.info(f"Tunnel {count} set successfully")
        else:
            logger.error(f"Failed to set tunnel {count}: {response.text}")

        xpath2 = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/config/devices/entry[@name='localhost.localdomain']/vsys/entry[@name='vsys1']/import/network/interface"
        element2 = f"<member>tunnel.{count}</member>"
        payload2 = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath2, 'element': element2}
        response2 = requests.post(self.base_url, params=payload2, verify=False)
        logger.debug(f'Request to set vsys: {payload2}')
        root = ET.fromstring(response2.content)
        status = root.find('.//msg').text
        if "command succeeded" in status:
            logger.info(f"Tunnel {count} added to vsys1")
        else:
            logger.error(f"Failed to set tunnel {count}: {response.text}")

        xpath3 = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/config/devices/entry[@name='localhost.localdomain']/network/virtual-router/entry[@name='{vr_name}']/interface"
        element3 = f"<member>tunnel.{count}</member>"
        payload3 = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath3, 'element': element3}
        response3 = requests.post(self.base_url, params=payload3, verify=False)
        logger.debug(f'Request to set vsys: {payload3}')
        root = ET.fromstring(response3.content)
        status = root.find('.//msg').text
        if "command succeeded" in status:
            logger.info(f"Tunnel {count} added to VR: {vr_name}")
            self.set_zone(logger, count, ike_gw_name, ipsec_prof_name)
            count += 1
        else:
            logger.error(f"Failed to set tunnel {count}: {response.text}")

    def set_zone(self, logger, tunnel, ike_gw_name, ipsec_prof_name):
        zone = self.config['palo_alto']['panorama']['BranchZone']
        tunnel_name = f'tunnel.{tunnel}'

        xpath = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/config/devices/entry[@name='localhost.localdomain']/vsys/entry[@name='vsys1']/zone/entry[@name='{zone}']/network/layer3"
        element = f"<member>{tunnel_name}</member>"
        payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
        logger.debug(f"Request to Panorama: {payload}")
        response = requests.post(self.base_url, params=payload, verify=False)

        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        if "command succeeded" in status:
            logger.info(f"Tunnel {tunnel_name} zone set successfully")
            self.set_ipsec_tunnel(logger, tunnel_name, ike_gw_name, ipsec_prof_name)
        else:
            logger.error(f"Failed to update tunnel zone {tunnel_name}: {response.text}")

    def set_ipsec_tunnel(self, logger, tunnel_name, ike_gw_name, ipsec_prof_name):
        # Set all variables to template based on the first instance, eventually each device will be overwritten.
        # Extract only the keys that start with 'site'
        ipsec_name =ike_gw_name.replace('IKE_GW','IPSEC')
        xpath = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/config/devices/entry[@name='localhost.localdomain']/network/tunnel/ipsec/entry[@name='{ipsec_name}']"
        element = f"<tunnel-interface>{tunnel_name}</tunnel-interface><auto-key><ipsec-crypto-profile>{ipsec_prof_name}</ipsec-crypto-profile><ike-gateway><entry name='{ike_gw_name}'/></ike-gateway></auto-key>"
        payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
        logger.debug(f"Request to Panorama: {payload}")
        response = requests.post(self.base_url, params=payload, verify=False)
        
        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        if status == "command succeeded":
            logger.info(f"IPsec tunnel {ipsec_name} set {status}")
        else:
            logger.error(f"Response from Panorama:\n{response.text}")

    def get_devices(self, logger):
        devices_list = []
        try:
            headers = {'X-PAN-KEY': self.token}
            payload = {'type': 'op', 'cmd': '<show><devices><all/></devices></show>'}
            logger.debug(f"Request to Panorama: {headers}{payload}")
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

    def update_panorama_variables(self, logger, max_retries=240, delay=15):
        # Initialize all devices in state_data as not connected
        for _, details in self.state_data.items():
            details['is_connected'] = False

        for attempt in range(max_retries):
            all_connected = True
            devices = self.get_devices(logger)  # Fetch devices from Panorama

            # Check and update the connection status for each device in state_data
            for region, details in self.state_data.items():
                matched_device = next((device for device in devices if device['ipv4'] == details['mgmt_ip']), None)
                if matched_device:
                    details['is_connected'] = True
                    details['serial'] = matched_device['serial']  # Update state_data with serial number
                    # Update Panorama variables for the matched device
                    self.update_device_variables(matched_device['serial'], details, logger)
                else:
                    all_connected = False  # Not all devices are connected yet

            if all_connected:
                logger.info("All devices in state_data are connected to Panorama.")
                break  # Exit the loop if all devices are connected
            else:
                logger.info(f'Waiting for all devices to connect. Retrying in {delay} seconds...Attempt: {attempt + 1} of Max Attempts: {max_retries}')
                time.sleep(delay)

        if not all_connected:
            logger.error("Not all devices in state_data connected to Panorama within the retry limit.")

    def update_device_variables(self, serial, details, logger):
        logger.info(f"Processing device with serial {serial} and management IP {details['mgmt_ip']}")
        self.update_variable(serial, '$trust_ip', details['trust_ip'], logger)
        self.update_variable(serial, '$trust_ip_base', details['trust_ip_base'], logger)
        self.update_variable(serial, '$trust_secondary_ip', details['trust_secondary_ip'], logger)
        self.update_variable(serial, '$untrust_ip', details['untrust_ip'], logger)
        self.update_variable(serial, '$untrust_ip_base', details['untrust_ip_base'], logger)
        self.update_variable(serial, '$untrust_router_id', details['untrust_router_id'], logger)
        self.update_variable(serial, '$trust_nexthop', details['trust_nexthop'], logger)
        self.update_variable(serial, '$untrust_nexthop', details['untrust_nexthop'], logger)
        self.update_variable(serial, '$public_untrust_ip', details['public_untrust_ip'], logger)
        self.update_variable(serial, '$gp_pool', details['gp_pool'], logger)
        logger.info(f"Updated variables for device with serial {serial}.")

    def update_variable(self, serial, variable_name, value, logger):
        # XPath
        xpath = f"/config/devices/entry[@name='localhost.localdomain']/template-stack/entry[@name='{self.stack_name}']/devices/entry[@name='{serial}']/variable/entry[@name='{variable_name}']/type"
        # XML element
        element = f"<ip-netmask>{value}</ip-netmask>"
        # Payload
        payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
        # Log the request content
        logger.debug(f"Request to Panorama: {payload}")
        # Make the request and log the response
        response = requests.post(self.base_url, params=payload, verify=False)
        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        if status == "command succeeded":
            logger.info(f"Variable device override {variable_name} set {status}")
        else:
            logger.error(f"Response from Panorama:\n{response.text}")
    
    def commit_panorama(self, logger):
        payload = {'type': 'commit', 'cmd': '<commit></commit>', 'key': self.token }
        response = requests.post(self.base_url, params=payload, verify=False)
        logger.info(f"Response from commit operation:\n{response.text}")
        
        # Parse the response and extract the job ID
        root = ET.fromstring(response.content)
        job_id = root.find('.//result/job').text if root.find('.//result/job') is not None else None
        return job_id

    def commit_dg_tpl_stack(self, logger, delay=2):
        cmd = f'<commit-all><shared-policy><force-template-values>yes</force-template-values><device-group><entry name="{self.dg_name}"/></device-group></shared-policy></commit-all>'
        payload = {'type': 'commit','action': 'all','cmd': cmd,'key': self.token}
        logger.info(f'Waiting {delay} seconds for devices to stablize during onboarding')
        time.sleep(delay)
        response = requests.post(self.base_url, params=payload, verify=False)
        logger.info(f"Response from commit-all operation:\n{response.text}")

        # Parse the response and extract the job ID
        root = ET.fromstring(response.content)
        job_id = root.find('.//result/job').text if root.find('.//result/job') is not None else None
        return job_id

    def check_commit_status(self, job_id, logger, max_retries=30, delay=10):
        for attempt in range(max_retries):
            cmd = f'<show><jobs><id>{job_id}</id></jobs></show>'
            payload = {'type': 'op', 'cmd': cmd, 'key': self.token}
            response = requests.post(self.base_url, params=payload, verify=False)
            logger.info(f"Response from job status check:\n{response.text}")

            root = ET.fromstring(response.content)
            status = root.find('.//result/job/status').text if root.find('.//result/job/status') is not None else None

            if status == 'FIN':
                job_result = root.find('.//result/job/result').text if root.find('.//result/job/result') is not None else None
                devices = root.findall('.//result/job/devices/entry')
                pending_devices = [device for device in devices if device.find('result').text == 'PEND']

                if job_result == 'FAIL' and not pending_devices:
                    # Handle the case where job failed but no devices are pending, meaning all have processed but some failed.
                    logger.info("Commit job completed with failures, but all relevant devices processed.")
                    return False

                if not pending_devices:
                    logger.info(f"Commit job {job_id} completed successfully.")
                    return True
                else:
                    logger.info("Some devices are still pending. Waiting for completion.")
                    time.sleep(delay)
                    continue  # Wait for pending devices to complete

            elif status in ['ACT', 'PEND']:
                logger.info(f"Commit job {job_id} is still in progress. Waiting {delay} seconds before next check.")
                time.sleep(delay)
            else:
                logger.error(f"Commit job {job_id} failed or status is unknown.")
                return False

        logger.error(f"Maximum retries reached for commit job {job_id} status check without all devices completing.")
        return False

    def update_panorama(self):
        # Disable SSL warnings
        urllib3.disable_warnings()
        
        # Get the logger
        logger = logging.getLogger()

        # # Set Template Variables
        self.set_base_variable(logger)

        # Set Crypto Profiles and Settings
        self.set_ipsec_crypto_profile(logger)

        # Call methods to update Panorama variables
        self.update_panorama_variables(logger)

        # Committing changes to Panorama
        job_id = self.commit_panorama(logger)
        if job_id and self.check_commit_status(job_id, logger):
            logger.info("Proceeding with commit-all to template stack.")
            commit_all_job_id = self.commit_dg_tpl_stack(logger)
            if commit_all_job_id:
                self.check_commit_status(commit_all_job_id, logger)