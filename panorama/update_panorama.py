# project/scripts/update_panorama.py
import requests
import xml.etree.ElementTree as ET
import urllib3
import logging
import time
import json

class UpdatePanorama:
    def __init__(self, config, token, base_url, state_data):
        self.config = config
        self.token = token
        self.base_url = base_url
        self.state_data = state_data
        self.license_manager = self.config['palo_alto']['panorama']['LicenseManager']
        self.template = self.config['palo_alto']['panorama']['PanoramaTemplate']
        self.stack_name = self.config['palo_alto']['panorama']['PanoramaTemplateStack']
        self.dg_name = self.config['palo_alto']['panorama']['PanoramaDeviceGroup']
        self.outside_vr_name = self.config['palo_alto']['panorama']['OutsideVirtualRouter']
        self.untrust_zone = self.config['palo_alto']['panorama']['UntrustZone']
        self.trust_zone = self.config['palo_alto']['panorama']['TrustZone']
        self.inside_vr_name = self.config['palo_alto']['panorama']['InsideVirtualRouter']
        self.ipsec_prof_name = self.template + "_" + self.config['vpn']['crypto_settings']['ipsec_crypto']['name']
        self.ike_prof_name = self.template + "_" + self.config['vpn']['crypto_settings']['ike_crypto']['name']

    def fetch_devices_from_template_stack(self, logger):
        headers = {
            'X-PAN-KEY': self.token,
            'Content-Type': 'application/x-www-form-urlencoded'  # Ensure headers are correctly set
        }
        
        payload = {
            'type': 'config',
            'action': 'get',  
            'xpath': f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.stack_name}']/devices"
        }
        logger.info(f"Fetching devices from template stack: {self.stack_name}")
        
        response = requests.post(self.base_url, headers=headers, data=payload, verify=True)
        logger.debug(f'Get device template stack Response: {response.content}')
        devices = {}
        try:
            root = ET.fromstring(response.content)
            device_entries_xpath = ".//devices/entry"
            for device_entry in root.findall(device_entries_xpath):
                serial = device_entry.get('name')
                public_untrust_ip_xpath = "./variable/entry[@name='$public_untrust_ip']/type/ip-netmask"
                public_untrust_ip_element = device_entry.find(public_untrust_ip_xpath)
                if public_untrust_ip_element is not None:
                    public_untrust_ip = public_untrust_ip_element.text
                    devices[serial] = public_untrust_ip
                    logger.debug(f"Device {serial} with public_untrust_ip: {public_untrust_ip}")
                else:
                    logger.debug(f"Device {serial} does not have a public_untrust_ip defined.")

            if devices:
                logger.info("Devices fetched successfully.")
            else:
                logger.info("No devices found or no devices with a defined public_untrust_ip.")
        except Exception as e:
            logger.error(f"Failed to fetch devices: {e}")

        logger.info(f'Fetched device serial numbers and public_untrust_ips: {devices}')
        return devices

    def deactivate_license_if_unmatched(self, devices, logger, delay=45):
        logger.info(f'Devices seen when calling deactivate_license_if_unmatched: {devices}')
        unmatched_devices = {serial: ip for serial, ip in devices.items() if ip not in [d['public_untrust_ip'] for d in self.state_data.values()]}

        for serial, public_untrust_ip in unmatched_devices.items():
            logger.info(f"Attempting to deactivate license for device {serial} with unmatched IP {public_untrust_ip}.")
            cmd = f'<request><plugins><sw_fw_license><deactivate><license-manager>{self.license_manager}</license-manager><devices><member>{serial}</member></devices></deactivate></sw_fw_license></plugins></request>'
            payload = {'type': 'op', 'cmd': cmd, 'key': self.token}

            response = requests.post(self.base_url, data=payload, verify=True)  # Note: using `data` for POST body
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                status_message = "".join(root.itertext())
                if "Deactivation request sent. Check system logs for status." in status_message:
                    logger.info(f"License deactivation request sent for device {serial}.")
                else:
                    logger.error(f"Deactivation request for device {serial} might not have been successful. Response: {status_message}")
            else:
                logger.error(f"Failed to send deactivation request for device {serial}. HTTP Status: {response.status_code}")

            time.sleep(delay)  # Rate-limiting deactivation requests

        # After processing all unmatched devices, attempt to commit changes on Panorama if any devices were deactivated
        if unmatched_devices:
            logger.info(f"Processed deactivation for {len(unmatched_devices)} unmatched devices. Initiating commit to Panorama.")
            job_id = self.commit_panorama(logger)
            if job_id:
                logger.info(f"Commit job to Panorama initiated with job-id: {job_id}.")
                if self.check_commit_status(job_id, logger):
                    logger.info("Commit job to Panorama completed successfully.")
                else:
                    logger.error("Commit job to Panorama did not complete successfully.")
            else:
                logger.error("Failed to initiate commit job to Panorama.")
        else:
            logger.info("No unmatched devices found for deactivation. No commit to Panorama required.")

    def set_base_variable(self, logger):
        # Set all variables to template based on the first instance, eventually each device will be overwritten.
        first_instance_data = next(iter(self.state_data.values()))
        for key, value in first_instance_data.items():
            variable_name = key
            xpath = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/variable/entry[@name='${variable_name}']/type"
            element = f"<ip-netmask>{value}</ip-netmask>"
            payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
            logger.debug(f"Request to Panorama: {payload}")
            response = requests.post(self.base_url, params=payload, verify=True)
            #
            root = ET.fromstring(response.content)
            status = root.find('.//msg').text
            if status == "command succeeded":
                logger.info(f"Variable {variable_name} set {status}")
            else:
                logger.error(f"Response from Panorama:\n{response.text}")

    def clean_existing_routing(self, logger):
        headers = {
            'X-PAN-KEY': self.token,
            'Content-Type': 'application/x-www-form-urlencoded'  # Ensure headers are correctly set
        }
        
        payload = {
            'type': 'config',
            'action': 'get',  
            'xpath': f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/config/devices/entry[@name='localhost.localdomain']/network/virtual-router/entry[@name='{self.inside_vr_name}']/protocol/bgp/peer-group"
        }
        
        response = requests.post(self.base_url, headers=headers, data=payload, verify=True)
        logger.debug(f"Fetching router: {self.inside_vr_name} and peer groups {response.text}")

        # Parse the XML response
        root = ET.fromstring(response.text)
        
        # Find all peer-group entries
        peer_groups = root.findall(".//peer-group/entry")        

        for pg in peer_groups:
            pg_name = pg.get('name')
            logger.info(f"Found peer group: {pg_name}")
            
            # Check if the entry name starts with your panorama template name
            if pg_name.startswith(self.template):
                logger.info(f"Deleting peer group: {pg_name}")
                self.delete_peer_group(logger, pg_name)

    def delete_peer_group(self, logger, pg_name):
        headers = {
            'X-PAN-KEY': self.token,
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        payload = {
            'type': 'config',
            'action': 'delete',
            'xpath': f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='PPA-TPL']/config/devices/entry[@name='localhost.localdomain']/network/virtual-router/entry[@name='{self.inside_vr_name}']/protocol/bgp/peer-group/entry[@name='{pg_name}']"
        }
        
        response = requests.post(self.base_url, headers=headers, data=payload, verify=True)
        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        if status == "command succeeded":
            logger.debug(f"Deleted peer group: {pg_name}")
        else:
            logger.error(f"Response from Panorama deleting peer group {pg_name}:\n{response.text}")            

    def set_interface(self, logger, count, router, ip_addr, ip_addr_secondary, zone, route_name, dest_route, peer_router):

        xpath = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/config/devices/entry[@name='localhost.localdomain']/network/interface/ethernet/entry[@name='ethernet1/{count}']/layer3/ip"
        element = f"<entry name='{ip_addr}'/>"
        payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
        logger.debug(f"Request to Panorama: {payload}")
        response = requests.post(self.base_url, params=payload, verify=True)

        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        if "command succeeded" in status:
            logger.info(f"Ethernet/{count} set successfully")
        else:
            logger.error(f"Failed to set Ethernet/{count}: {response.text}")

        xpath = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/config/devices/entry[@name='localhost.localdomain']/network/interface/loopback/units/entry[@name='loopback.{count}']/ip"
        element = f"<entry name='{ip_addr_secondary}'/>"
        payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
        logger.debug(f"Request to Panorama: {payload}")
        response = requests.post(self.base_url, params=payload, verify=True)

        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        logger.debug(f'Loopback response: {response.content}')
        if "command succeeded" in status:
            logger.info(f"loopback.{count} set successfully")
        else:
            logger.error(f"Failed to set loopback.{count}: {response.text}")

        xpath = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/config/devices/entry[@name='localhost.localdomain']/vsys/entry[@name='vsys1']/zone/entry[@name='{zone}']/network/layer3"
        element = f"<member>ethernet1/{count}</member>"
        payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
        logger.debug(f"Request to Panorama: {payload}")
        response = requests.post(self.base_url, params=payload, verify=True)

        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        if "command succeeded" in status:
            logger.info(f"Ethernet1/{count} zone set successfully")
        else:
            logger.error(f"Failed to update interface zone ethernet1/{count}: {response.text}")

        xpath = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/config/devices/entry[@name='localhost.localdomain']/vsys/entry[@name='vsys1']/import/network/interface"
        element = f"<member>ethernet1/{count}</member>"
        payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
        response = requests.post(self.base_url, params=payload, verify=True)
        logger.debug(f'Request to set vsys: {payload}')
        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        if "command succeeded" in status:
            logger.info(f"Ethernet/{count} added to vsys1")
        else:
            logger.error(f"Failed to set ethernet/{count}: {response.text}")

        xpath = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/config/devices/entry[@name='localhost.localdomain']/network/virtual-router/entry[@name='{router}']/interface"
        element = f"<member>ethernet1/{count}</member>"
        payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
        response = requests.post(self.base_url, params=payload, verify=True)
        logger.debug(f'Request to set vsys: {payload}')
        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        if "command succeeded" in status:
            logger.info(f"Ethernet/{count} added to VR: {router}")
        else:
            logger.error(f"Failed to set ethernet/{count} to router {router}: {response.text}")

        if count == 1:
            xpath = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/config/devices/entry[@name='localhost.localdomain']/network/virtual-router/entry[@name='{router}']/routing-table/ip/static-route/entry[@name='Default']"
            element = f"<nexthop><ip-address>$untrust_nexthop</ip-address></nexthop><bfd><profile>None</profile></bfd><metric>10</metric><destination>0.0.0.0/0</destination><route-table><unicast/></route-table>"
            payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
            logger.debug(f"Request to Panorama: {payload}")
            response = requests.post(self.base_url, params=payload, verify=True)
            
            root = ET.fromstring(response.content)
            status = root.find('.//msg').text
            if status == "command succeeded":
                logger.info(f"Router {router} default route set {status}")
            else:
                logger.error(f"Bad route command, Response from Panorama:\n{response.text}")   
        if count == 2:
            xpath = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/config/devices/entry[@name='localhost.localdomain']/network/virtual-router/entry[@name='{router}']/routing-table/ip/static-route/entry[@name='Default']"
            element = f"<nexthop><next-vr>{peer_router}</next-vr></nexthop><bfd><profile>None</profile></bfd><metric>10</metric><destination>0.0.0.0/0</destination><route-table><unicast/></route-table>"
            payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
            logger.debug(f"Request to Panorama: {payload}")
            response = requests.post(self.base_url, params=payload, verify=True)
            
            root = ET.fromstring(response.content)
            status = root.find('.//msg').text
            if status == "command succeeded":
                logger.info(f"Router {router} default route set {status}")
            else:
                logger.error(f"Bad route command, Response from Panorama:\n{response.text}") 

        xpath = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/config/devices/entry[@name='localhost.localdomain']/network/virtual-router/entry[@name='{router}']/routing-table/ip/static-route/entry[@name='{route_name}']"
        element = f"<nexthop><next-vr>{peer_router}</next-vr></nexthop><bfd><profile>None</profile></bfd><metric>10</metric><destination>{dest_route}</destination><route-table><unicast/></route-table>"
        payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
        logger.debug(f"Request to Panorama: {payload}")
        response = requests.post(self.base_url, params=payload, verify=True)
        
        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        if status == "command succeeded":
            logger.info(f"Peer Loopback {dest_route} route set {status}")
        else:
            logger.error(f"Bad route command, Response from Panorama:\n{response.text}")    

    def set_ipsec_crypto_profile(self, logger):
        auth = self.config['vpn']['crypto_settings']['ipsec_crypto']['auth']
        dh_group = self.config['vpn']['crypto_settings']['ipsec_crypto']['dh_group']
        encryption = self.config['vpn']['crypto_settings']['ipsec_crypto']['encryption']
        xpath = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/config/devices/entry[@name='localhost.localdomain']/network/ike/crypto-profiles/ipsec-crypto-profiles/entry[@name='{self.ipsec_prof_name}']"
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
        response = requests.post(self.base_url, params=payload, verify=True)
        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        if status == "command succeeded":
            logger.info(f"Ipsec Profile {self.ipsec_prof_name} set {status}")               
        else:
            logger.error(f"Response from Panorama:\n{response.text}")


    def set_ike_crypto_profile(self, logger):
        # Set all variables to template based on the first instance, eventually each device will be overwritten.
        # prof_name = self.config['vpn']['crypto_settings']['ike_crypto']['name']
        # ike_prof_name = f'{self.template}_{prof_name}'
        auth = self.config['vpn']['crypto_settings']['ike_crypto']['auth']
        dh_group = self.config['vpn']['crypto_settings']['ike_crypto']['dh_group']
        encryption = self.config['vpn']['crypto_settings']['ike_crypto']['encryption']
        xpath = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/config/devices/entry[@name='localhost.localdomain']/network/ike/crypto-profiles/ike-crypto-profiles/entry[@name='{self.ike_prof_name}']"
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
        response = requests.post(self.base_url, params=payload, verify=True)
        #
        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        if status == "command succeeded":
            logger.info(f"Ike Profile {self.ike_prof_name} set {status}")
        else:
            logger.error(f"Response from Panorama:\n{response.text}")

    def set_ike_gateway(self, logger, site, details, count):
        logger.info(f"Processing {site} with IP address {details['ike_peer_ip']} and Loopback {details['bgp_peer_ip']}")
        ike_gw_name = self.template + "_" + site
        psk = self.config['vpn']['crypto_settings']['ike_gw']['psk']
        bgp_peer_ip = details['bgp_peer_ip']
        ike_peer_ip = details['ike_peer_ip']
        bgp_peer_as = details['as_number']
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
                    <ike-crypto-profile>{self.ike_prof_name}</ike-crypto-profile>
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
                <ip>{ike_peer_ip}</ip>
            </peer-address>
            <local-id>
                <id>$untrust_ip_base</id>
                <type>ipaddr</type>
            </local-id>"""
        payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
        logger.debug(f"Request to Panorama: {payload}")
        response = requests.post(self.base_url, params=payload, verify=True)  # Remember to handle SSL verification appropriately

        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        logger.info(f'Status of setting ike gateway: {status}')
        if "command succeeded" in status:
            logger.info(f"Ike Gateway {ike_gw_name} set {status}")
            self.set_tunnel_interface(logger, count, ike_gw_name, bgp_peer_ip, bgp_peer_as)
        else:
            logger.error(f"Response from Panorama:\n{response.text}")
            return
        # else:
        #     logger.info(f'No site data in VPN config')

    def set_tunnel_interface(self, logger, count, ike_gw_name, bgp_peer_ip, bgp_peer_as):

        xpath = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/config/devices/entry[@name='localhost.localdomain']/network/interface/tunnel/units"
        element = f"<entry name='tunnel.{count}'/>"
        payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
        logger.debug(f"Request to Panorama: {payload}")
        response = requests.post(self.base_url, params=payload, verify=True)

        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        if "command succeeded" in status:
            logger.info(f"Tunnel {count} set successfully")
        else:
            logger.error(f"Failed to set tunnel {count}: {response.text}")

        xpath2 = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/config/devices/entry[@name='localhost.localdomain']/vsys/entry[@name='vsys1']/import/network/interface"
        element2 = f"<member>tunnel.{count}</member>"
        payload2 = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath2, 'element': element2}
        response2 = requests.post(self.base_url, params=payload2, verify=True)
        logger.debug(f'Request to set vsys: {payload2}')
        root = ET.fromstring(response2.content)
        status = root.find('.//msg').text
        if "command succeeded" in status:
            logger.info(f"Tunnel {count} added to vsys1")
        else:
            logger.error(f"Failed to set tunnel {count}: {response.text}")

        xpath3 = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/config/devices/entry[@name='localhost.localdomain']/network/virtual-router/entry[@name='{self.inside_vr_name}']/interface"
        element3 = f"<member>tunnel.{count}</member>"
        payload3 = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath3, 'element': element3}
        response3 = requests.post(self.base_url, params=payload3, verify=True)
        logger.debug(f'Request to set vsys: {payload3}')
        root = ET.fromstring(response3.content)
        status = root.find('.//msg').text
        if "command succeeded" in status:
            logger.info(f"Tunnel {count} added to VR: {self.inside_vr_name}")
            self.set_zone(logger, count, ike_gw_name, bgp_peer_ip, bgp_peer_as)
            count += 1
        else:
            logger.error(f"Failed to set tunnel {count}: {response.text}")

    def set_zone(self, logger, tunnel, ike_gw_name, bgp_peer_ip, bgp_peer_as):
        zone = self.config['palo_alto']['panorama']['BranchZone']
        tunnel_name = f'tunnel.{tunnel}'

        xpath = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/config/devices/entry[@name='localhost.localdomain']/vsys/entry[@name='vsys1']/zone/entry[@name='{zone}']/network/layer3"
        element = f"<member>{tunnel_name}</member>"
        payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
        logger.debug(f"Request to Panorama: {payload}")
        response = requests.post(self.base_url, params=payload, verify=True)

        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        if "command succeeded" in status:
            logger.info(f"Tunnel {tunnel_name} zone set successfully")
            self.set_ipsec_tunnel(logger, tunnel_name, ike_gw_name, bgp_peer_ip, bgp_peer_as)
        else:
            logger.error(f"Failed to update tunnel zone {tunnel_name}: {response.text}")

    def set_ipsec_tunnel(self, logger, tunnel_name, ike_gw_name, bgp_peer_ip, bgp_peer_as):
        # Set all variables to template based on the first instance, eventually each device will be overwritten.
        # Extract only the keys that start with 'site'
        ipsec_name =ike_gw_name.replace('IKE_GW','IPSEC')
        xpath = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/config/devices/entry[@name='localhost.localdomain']/network/tunnel/ipsec/entry[@name='{ipsec_name}']"
        element = f"<tunnel-interface>{tunnel_name}</tunnel-interface><auto-key><ipsec-crypto-profile>{self.ipsec_prof_name}</ipsec-crypto-profile><ike-gateway><entry name='{ike_gw_name}'/></ike-gateway></auto-key>"
        payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
        logger.debug(f"Request to Panorama: {payload}")
        response = requests.post(self.base_url, params=payload, verify=True)
        
        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        if status == "command succeeded":
            logger.info(f"IPsec tunnel {ipsec_name} set {status}")
            self.set_tunnel_static_route(logger, tunnel_name, ike_gw_name, bgp_peer_ip, bgp_peer_as)
        else:
            logger.error(f"Response from Panorama:\n{response.text}")

    def set_tunnel_static_route(self, logger, tunnel_name, ike_gw_name, bgp_peer_ip, bgp_peer_as):
        xpath = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/config/devices/entry[@name='localhost.localdomain']/network/virtual-router/entry[@name='{self.inside_vr_name}']/routing-table/ip/static-route/entry[@name='{ike_gw_name}']"
        element = f"<bfd><profile>None</profile></bfd><interface>{tunnel_name}</interface><metric>10</metric><destination>{bgp_peer_ip}/32</destination><route-table><unicast/></route-table>"
        payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
        logger.debug(f"Request to Panorama: {payload}")
        response = requests.post(self.base_url, params=payload, verify=True)
        
        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        if status == "command succeeded":
            logger.info(f"Peer Loopback {bgp_peer_ip} route set {status}")
            self.set_bgp_peer_group(logger, ike_gw_name, bgp_peer_ip, bgp_peer_as)
        else:
            logger.error(f"Response from Panorama:\n{response.text}")            

    def set_bgp_peer_group(self, logger, ike_gw_name, bgp_peer_ip, bgp_peer_as):
        xpath = f"/config/devices/entry[@name='localhost.localdomain']/template/entry[@name='{self.template}']/config/devices/entry[@name='localhost.localdomain']/network/virtual-router/entry[@name='{self.inside_vr_name}']/protocol/bgp/peer-group/entry[@name='{ike_gw_name}']"
        element = f"""
        <type>
            <ebgp>
                <remove-private-as>no</remove-private-as>
                <import-nexthop>original</import-nexthop>
                <export-nexthop>resolve</export-nexthop>
            </ebgp>
        </type>
        <peer>
            <entry name="{ike_gw_name}-Peer">
                <peer-address>
                    <ip>{bgp_peer_ip}</ip>
                </peer-address>
                <connection-options>
                    <incoming-bgp-connection>
                        <remote-port>0</remote-port>
                        <allow>yes</allow>
                    </incoming-bgp-connection>
                    <outgoing-bgp-connection>
                        <local-port>0</local-port>
                        <allow>yes</allow>
                    </outgoing-bgp-connection>
                    <multihop>2</multihop>
                    <keep-alive-interval>30</keep-alive-interval>
                    <open-delay-time>0</open-delay-time>
                    <hold-time>90</hold-time>
                    <idle-hold-time>15</idle-hold-time>
                    <min-route-adv-interval>30</min-route-adv-interval>
                </connection-options>
                <subsequent-address-family-identifier>
                    <unicast>yes</unicast>
                    <multicast>no</multicast>
                </subsequent-address-family-identifier>
                <local-address>
                    <ip>$trust_secondary_ip</ip>
                    <interface>loopback.2</interface>
                </local-address>
                <bfd>
                    <profile>Inherit-vr-global-setting</profile>
                </bfd>
                <max-prefixes>5000</max-prefixes>
                <enable>yes</enable>
                <peer-as>{bgp_peer_as}</peer-as>
                <enable-mp-bgp>no</enable-mp-bgp>
                <address-family-identifier>ipv4</address-family-identifier>
                <enable-sender-side-loop-detection>yes</enable-sender-side-loop-detection>
                <reflector-client>non-client</reflector-client>
                <peering-type>unspecified</peering-type>
            </entry>
        </peer>
        <aggregated-confed-as-path>yes</aggregated-confed-as-path>
        <soft-reset-with-stored-info>no</soft-reset-with-stored-info>
        <enable>yes</enable>
        """.strip()
        payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
        logger.debug(f"Request to Panorama: {payload}")
        response = requests.post(self.base_url, params=payload, verify=True)
        
        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        if status == "command succeeded":
            logger.info(f"BGP PeerGroup {ike_gw_name} set {status}")
        else:
            logger.error(f"Response from Panorama:\n{response.text}")
  
    def get_devices(self, logger):
        devices_list = []
        try:
            headers = {'X-PAN-KEY': self.token}
            payload = {'type': 'op', 'cmd': '<show><devices><all/></devices></show>'}
            logger.debug(f"Request to Panorama: {headers}{payload}")
            response = requests.post(self.base_url, headers=headers, params=payload, verify=True)
            logger.debug(f"Response from Panorama:\n{response.text}")
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
        # Initialize all devices in state_data as not connected and not updated
        for _, details in self.state_data.items():
            details['is_connected'] = False # Assume device is not connected
            details['is_updated'] = False  # Add an is_updated flag

        for attempt in range(max_retries):
            all_connected = True
            devices = self.get_devices(logger)  # Fetch devices from Panorama

            for region, details in self.state_data.items():
                if not details.get('is_updated'):  # Check if device hasn't been updated yet
                    matched_device = next((device for device in devices if device['ipv4'] == details['mgmt_ip']), None)
                    if matched_device:
                        details['is_connected'] = True
                        details['serial'] = matched_device['serial']
                        if not details.get('is_updated'):  # Ensure update_device_variables is called only once
                            self.update_device_variables(matched_device['serial'], details, logger)
                            details['is_updated'] = True  # Mark as updated
                    else:
                        all_connected = False

            if all_connected:
                logger.info("All devices in state_data are connected to Panorama.")
                break
            else:
                logger.info(f'Waiting for all devices to connect. Retrying in {delay} seconds...Attempt: {attempt + 1} of Max Attempts: {max_retries}')
                time.sleep(delay)

        if not all_connected:
            logger.error("Not all devices in state_data connected to Panorama within the retry limit.")

    def update_device_variables(self, serial, details, logger):
        logger.info(f"Processing device with serial {serial} and management IP {details['mgmt_ip']}")
        self.update_ipnetmask_variable(serial, '$trust_ip', details['trust_ip'], logger)
        self.update_ipnetmask_variable(serial, '$trust_ip_base', details['trust_ip_base'], logger)
        self.update_ipnetmask_variable(serial, '$trust_secondary_ip', details['trust_secondary_ip'], logger)
        self.update_ipnetmask_variable(serial, '$untrust_ip', details['untrust_ip'], logger)
        self.update_ipnetmask_variable(serial, '$untrust_ip_base', details['untrust_ip_base'], logger)
        self.update_ipnetmask_variable(serial, '$untrust_router_id', details['untrust_router_id'], logger)
        self.update_ipnetmask_variable(serial, '$trust_nexthop', details['trust_nexthop'], logger)
        self.update_ipnetmask_variable(serial, '$untrust_nexthop', details['untrust_nexthop'], logger)
        self.update_ipnetmask_variable(serial, '$public_untrust_ip', details['public_untrust_ip'], logger)
        self.update_ipnetmask_variable(serial, '$vpn_user_pool', details['vpn_user_pool'], logger)
        self.update_as_variable(serial, '$eBGP_AS', details['eBGP_AS'], logger)
        logger.info(f"Updated variables for device with serial {serial}.")

    def update_ipnetmask_variable(self, serial, variable_name, value, logger):
        # XPath
        xpath = f"/config/devices/entry[@name='localhost.localdomain']/template-stack/entry[@name='{self.stack_name}']/devices/entry[@name='{serial}']/variable/entry[@name='{variable_name}']/type"
        # XML element
        element = f"<ip-netmask>{value}</ip-netmask>"
        # Payload
        payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
        # Log the request content
        logger.debug(f"Request to Panorama: {payload}")
        # Make the request and log the response
        response = requests.post(self.base_url, params=payload, verify=True)
        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        if status == "command succeeded":
            logger.info(f"Variable device override {variable_name} set {status}")
        else:
            logger.error(f"Response from Panorama:\n{response.text}")

    def update_as_variable(self, serial, variable_name, value, logger):
        # XPath
        xpath = f"/config/devices/entry[@name='localhost.localdomain']/template-stack/entry[@name='{self.stack_name}']/devices/entry[@name='{serial}']/variable/entry[@name='{variable_name}']/type"
        # XML element
        element = f"<as-number>{value}</as-number>"
        # Payload
        payload = {'type': 'config', 'action': 'set', 'key': self.token, 'xpath': xpath, 'element': element}
        # Log the request content
        logger.debug(f"Request to Panorama: {payload}")
        # Make the request and log the response
        response = requests.post(self.base_url, params=payload, verify=True)
        root = ET.fromstring(response.content)
        status = root.find('.//msg').text
        if status == "command succeeded":
            logger.info(f"Variable device override {variable_name} set {status}")
        else:
            logger.error(f"Response from Panorama:\n{response.text}")

    def commit_panorama(self, logger):
        payload = {'type': 'commit', 'cmd': '<commit></commit>', 'key': self.token }
        response = requests.post(self.base_url, params=payload, verify=True)
        logger.info(f"Response from commit operation:\n{response.text}")
        
        # Parse the response and extract the job ID
        root = ET.fromstring(response.content)
        job_id = root.find('.//result/job').text if root.find('.//result/job') is not None else None
        return job_id

    def commit_dg_tpl_stack(self, logger, delay=300, max_retries=3, initial_delay=3):
        # First, ensure all devices are connected
        logger.info(f'Waiting {initial_delay} seconds for devices to onboard to panorama')
        time.sleep(initial_delay)
        for attempt in range(max_retries):
            devices = self.get_devices(logger)  # Fetch devices from Panorama again
            all_connected = True

            for _, details in self.state_data.items():
                matched_device = next((device for device in devices if device['ipv4'] == details['mgmt_ip']), None)
                if not matched_device or not details.get('is_connected'):
                    all_connected = False
                    break  # Exit the loop early if any device is not connected

            if all_connected:
                logger.info("All devices are connected to Panorama. Proceeding with commit.")
                break  # Proceed with commit since all devices are connected
            else:
                logger.info(f"Waiting for all devices to connect. Retrying in {delay} seconds... Attempt: {attempt + 1}/{max_retries}")
                time.sleep(delay)

        if not all_connected:
            logger.error("Not all devices connected to Panorama within the retry limit. Aborting commit.")
            return None  # Return early if not all devices are connected

        # If all devices are connected, proceed with the commit
        retry_commit_count = 0
        while retry_commit_count < max_retries:
            cmd = f'<commit-all><shared-policy><force-template-values>yes</force-template-values><device-group><entry name="{self.dg_name}"/></device-group></shared-policy></commit-all>'
            payload = {'type': 'commit', 'action': 'all', 'cmd': cmd, 'key': self.token}
            logger.info(f"Initiating commit-all operation. Attempt: {retry_commit_count + 1}")
            response = requests.post(self.base_url, params=payload, verify=False)  # Ensure proper SSL verification in production
            logger.debug(f"Response from commit-all operation:\n{response.text}")

            root = ET.fromstring(response.content)
            job_id = root.find('.//result/job').text if root.find('.//result/job') is not None else None

            # Check commit status with a modified version that looks for specific errors
            commit_status, should_retry = self.check_commit_status(job_id, logger, max_retries=30, delay=10)
            if commit_status and not should_retry:
                return True
            elif not commit_status and should_retry:
                retry_commit_count += 1
                logger.info(f'Retrying commit-all operation due to specific errors detected. Retry attempt: {retry_commit_count}')
                time.sleep(delay)
            else:
                return False

        logger.error(f'Max retries reached for commit-all operation. Please check device connectivity and configuration.')
        return False

    def check_commit_status(self, job_id, logger, max_retries=30, delay=10):
        for attempt in range(max_retries):
            cmd = f'<show><jobs><id>{job_id}</id></jobs></show>'
            payload = {'type': 'op', 'cmd': cmd, 'key': self.token}
            response = requests.post(self.base_url, params=payload, verify=False)  # Ensure proper SSL verification in production
            logger.debug(f"Checking commit job {job_id} status: Attempt {attempt+1}")

            root = ET.fromstring(response.content)
            status = root.find('.//result/job/status').text if root.find('.//result/job/status') is not None else None

            if status == 'FIN':
                result = root.find('.//result/job/result').text
                errors = root.findall('.//errors/line')
                error_messages = [error.text for error in errors]

                # Identify specific errors
                specific_errors_detected = any("panw-bulletproof-ip-list" in message for message in error_messages)
                if result == 'FAIL' and specific_errors_detected:
                    logger.error(f"Specific errors detected in commit job {job_id}: {error_messages}")
                    return False, True  # Indicate a retry should occur
                elif result == 'FAIL':
                    logger.error(f"Commit job {job_id} failed with errors: {error_messages}")
                    return False, False
                else:
                    logger.info(f"Commit job {job_id} completed successfully.")
                    return True, False

            elif status in ['ACT', 'PEND']:
                logger.info(f"Commit job {job_id} is still in progress. Next check in {delay} seconds.")
                time.sleep(delay)
            else:
                logger.error(f"Commit job {job_id} failed or status is unknown. No retry.")
                return False, False

        logger.error(f"Maximum retries reached for commit job {job_id} status check. No further retries.")
        return False, False

    def update_panorama(self):
        # Disable SSL warnings
        urllib3.disable_warnings()
        
        # Get the logger
        logger = logging.getLogger()

        # Fetch devices from the template and their trust IPs
        devices = self.fetch_devices_from_template_stack(logger)
        
        # Deactivate licenses for devices with unmatched public IP... Note probably need better check mechnasim
        self.deactivate_license_if_unmatched(devices, logger)

        # # Delete pre-existing routing and ipsec
        self.clean_existing_routing(logger)

        # Check if state_data is empty before proceeding
        if not self.state_data:
            logger.info("No state data available. Committing changes to Panorama and exiting.")
            self.commit_panorama(logger)
            return  # Exit the method

        # # Set Template Variables
        self.set_base_variable(logger)

        # # Set Untrust ethernet Interfaces variables
        ethernet_count = 1
        untrust_router = self.config['palo_alto']['panorama']['OutsideVirtualRouter']
        untrust_ip_addr = '$untrust_ip'
        untrust_loopback = '$bgp_untrust_loopback'
        untrust_zone = self.untrust_zone
        untrust_route_name = 'Untrust-to-Trust'
        # # Set Trust ethernet Interfaces variables
        trust_router = self.config['palo_alto']['panorama']['InsideVirtualRouter']
        trust_ip_addr = '$trust_ip'
        trust_ip_base = '$trust_secondary_ip'
        trust_zone = self.trust_zone
        trust_route_name = 'Trust-to-Untrust'
        # # Send the set commands for interfaces and static routes
        self.set_interface(logger, ethernet_count, untrust_router, untrust_ip_addr, untrust_loopback, untrust_zone, untrust_route_name, trust_ip_base, trust_router)
        ethernet_count += 1
        self.set_interface(logger, ethernet_count, trust_router, trust_ip_addr, trust_ip_base, trust_zone, trust_route_name, untrust_loopback, untrust_router)

        # Set Crypto Profiles and Settings
        self.set_ipsec_crypto_profile(logger)
        self.set_ike_crypto_profile(logger)

        # Set IKE Gateway and IPsec stuff
        site_data = self.config['vpn']['on_prem_vpn_settings']
        count = 7500 #We'll use this for tunnel.XXXX interface ID
        logger.info(f'Site Data: {site_data}')
        for site, details in site_data.items():
            self.set_ike_gateway(logger, site, details, count)
            count += 1
        else:
            logger.info(f'No site data in VPN config')                 

        # Call methods to update Panorama variables
        self.update_panorama_variables(logger)

        # Committing changes to Panorama
        job_id = self.commit_panorama(logger)
        if job_id and self.check_commit_status(job_id, logger):
            logger.info("Proceeding with commit-all to DG and template stack.")
            commit_all_job_id = self.commit_dg_tpl_stack(logger)
            if commit_all_job_id:
                self.check_commit_status(commit_all_job_id, logger)