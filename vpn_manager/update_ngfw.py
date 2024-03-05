# project/scripts/update_ngfw.py
import requests
import xml.etree.ElementTree as ET
import urllib3
import logging
import time

class UpdateNGFW:
    def __init__(self, config, token, base_url, state_data):
        self.config = config
        self.token = token
        self.base_url = base_url
        self.state_data = state_data
        self.template = self.config['palo_alto']['panorama']['PanoramaTemplate']

    def set_ipsec_crypto_profile(self, logger):
        # Set all variables to template based on the first instance, eventually each device will be overwritten.
        prof_name = self.config['vpn']['crypto_settings']['ipsec_crypto']['name']
        ipsec_prof_name = f'{self.template}_{prof_name}'
        auth = self.config['vpn']['crypto_settings']['ipsec_crypto']['auth']
        dh_group = self.config['vpn']['crypto_settings']['ipsec_crypto']['dh_group']
        encryption = self.config['vpn']['crypto_settings']['ipsec_crypto']['encryption']
        xpath = f"/config/devices/entry[@name='localhost.localdomain']/network/ike/crypto-profiles/ipsec-crypto-profiles/entry[@name='{ipsec_prof_name}']"
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
        logger.debug(f"Request to NGFW: {payload}")
        response = requests.post(self.base_url, params=payload, verify=False)
        #
        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        if status == "command succeeded":
            logger.info(f"Ipsec Profile {ipsec_prof_name} set {status}")
            self.set_ike_crypto_profile(logger, ipsec_prof_name)
        else:
            logger.error(f"Response from NGFW:\n{response.text}")


    def set_ike_crypto_profile(self, logger, ipsec_prof_name):
        # Set all variables to template based on the first instance, eventually each device will be overwritten.
        prof_name = self.config['vpn']['crypto_settings']['ike_crypto']['name']
        ike_prof_name = f'{self.template}_{prof_name}'
        auth = self.config['vpn']['crypto_settings']['ike_crypto']['auth']
        dh_group = self.config['vpn']['crypto_settings']['ike_crypto']['dh_group']
        encryption = self.config['vpn']['crypto_settings']['ike_crypto']['encryption']
        xpath = f"/config/devices/entry[@name='localhost.localdomain']/network/ike/crypto-profiles/ike-crypto-profiles/entry[@name='{ike_prof_name}']"
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
        logger.debug(f"Request to NGFW: {payload}")
        response = requests.post(self.base_url, params=payload, verify=False)
        #
        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        if status == "command succeeded":
            logger.info(f"Ike Profile {ike_prof_name} set {status}")
            self.set_ike_gateway(logger, ike_prof_name, ipsec_prof_name)
        else:
            logger.error(f"Response from Ike Profile NGFW:\n{response.text}")

    def set_ike_gateway(self, logger, ike_prof_name, ipsec_prof_name):
        count = 7499
        # Assuming state_data is structured as mentioned, with each key representing a site and its details
        site_data = self.state_data
        logger.info(f'Site Data: {site_data}')
        
        for site_instance, details in site_data.items():
            # Extract the site name and public_untrust_ip for each instance
            site_name = site_instance  # Adjust based on actual naming convention if needed
            ip_addr = details.get('public_untrust_ip')
            if not ip_addr:
                logger.error(f"No public_untrust_ip found for {site_instance}")
                continue  # Skip to the next site if public_untrust_ip is missing
            
            logger.info(f"Processing {site_name} with IP address {ip_addr}")
            ike_gw_name = f'{site_name}'
            psk = self.config['vpn']['crypto_settings']['ike_gw']['psk']
            
            xpath = f"/config/devices/entry[@name='localhost.localdomain']/network/ike/gateway/entry[@name='{ike_gw_name}']"
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
                    <ip>{ip_addr}</ip>
                </peer-address>
                <peer-id>
                    <id>{details.get('untrust_ip_base')}</id>
                    <type>ipaddr</type>
                </peer-id>"""
            
            payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
            logger.debug(f"Request to NGFW: {payload}")
            response = requests.post(self.base_url, params=payload, verify=False)  # Ensure SSL verification is handled appropriately in production

            root = ET.fromstring(response.content)
            status = root.find('.//msg').text
            if "command succeeded" in status:
                logger.info(f"Ike Gateway {ike_gw_name} set successfully.")
                count += 1
                self.set_tunnel_interface(logger, count, ike_gw_name, ipsec_prof_name)
            else:
                logger.error(f"Response from NGFW:\n{response.text}")

    def set_tunnel_interface(self, logger, count, ike_gw_name, ipsec_prof_name):
        vr_name = self.config['palo_alto']['ngfw']['VirtualRouter']

        #Create the tunnel interface
        xpath = f"/config/devices/entry[@name='localhost.localdomain']/network/interface/tunnel/units"
        element = f"<entry name='tunnel.{count}'/>"
        payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
        logger.debug(f"Request to NGFW: {payload}")
        response = requests.post(self.base_url, params=payload, verify=False)

        #Assign tunnel interface to vsys
        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        if "command succeeded" in status:
            logger.info(f"Tunnel {count} set successfully")
        else:
            logger.error(f"Failed to set tunnel {count}: {response.text}")

        #Assign tunnel interface to router
        xpath3 = f"/config/devices/entry[@name='localhost.localdomain']/network/logical-router/entry[@name='{vr_name}']/vrf/entry[@name='{vr_name}']/interface"
        element3 = f"<member>tunnel.{count}</member>"
        payload3 = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath3, 'element': element3}
        response3 = requests.post(self.base_url, params=payload3, verify=False)
        logger.debug(f'Request to set vsys: {payload3}')
        root = ET.fromstring(response3.content)
        status = root.find('.//msg').text
        if "command succeeded" in status:
            logger.info(f"Tunnel {count} added to Router: {vr_name}")
            self.set_zone(logger, count, ike_gw_name, ipsec_prof_name)
            count += 1
        else:
            logger.error(f"Failed to set tunnel {count}: {response.text}")

    def set_zone(self, logger, tunnel, ike_gw_name, ipsec_prof_name):
        zone = self.config['palo_alto']['ngfw']['BranchZone']
        tunnel_name = f'tunnel.{tunnel}'

        xpath = f"/config/devices/entry[@name='localhost.localdomain']/vsys/entry[@name='vsys1']/zone/entry[@name='{zone}']/network/layer3"
        element = f"<member>{tunnel_name}</member>"
        payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
        logger.debug(f"Request to NGFW: {payload}")
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
        xpath = f"/config/devices/entry[@name='localhost.localdomain']/network/tunnel/ipsec/entry[@name='{ipsec_name}']"
        element = f"<tunnel-interface>{tunnel_name}</tunnel-interface><auto-key><ipsec-crypto-profile>{ipsec_prof_name}</ipsec-crypto-profile><ike-gateway><entry name='{ike_gw_name}'/></ike-gateway></auto-key>"
        payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
        logger.debug(f"Request to NGFW: {payload}")
        response = requests.post(self.base_url, params=payload, verify=False)
        
        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        if status == "command succeeded":
            logger.info(f"IPsec tunnel {ipsec_name} set {status}")
        else:
            logger.error(f"Response from NGFW:\n{response.text}")
    
    def commit_ngfw(self, logger):
        payload = {'type': 'commit', 'cmd': '<commit></commit>', 'key': self.token }
        response = requests.post(self.base_url, params=payload, verify=False)
        logger.info(f"Response from commit operation:\n{response.text}")
        
        # Parse the response and extract the job ID
        root = ET.fromstring(response.content)
        job_id = root.find('.//result/job').text if root.find('.//result/job') is not None else None
        return job_id

    def check_commit_status(self, job_id, logger, max_retries=30, delay=10):
        for attempt in range(max_retries):
            cmd = f'<show><jobs><id>{job_id}</id></jobs></show>'
            payload = {'type': 'op', 'cmd': cmd, 'key': self.token}
            response = requests.post(self.base_url, params=payload, verify=False)
            logger.debug(f"Response from job status check:\n{response.text}")

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

    def update_ngfw(self):
        # Disable SSL warnings
        urllib3.disable_warnings()
        
        # Get the logger
        logger = logging.getLogger()

        # Set Crypto Profiles and Settings
        self.set_ipsec_crypto_profile(logger)

        # Committing changes to NGFW
        job_id = self.commit_ngfw(logger)
        if job_id:
            self.check_commit_status(job_id, logger)