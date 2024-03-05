## Welcome
- **Purpose:** Create your own GlobalProtect automated solution on AWS(currently)
- **Assumptions:** 
  - **Panorama**: You have a Panorama, configured Template and Template Stack with two interfaces (eth1/1 and eth1/2), this is dual VR model for trust/untrust and VR are deployed. VR will bgp between to advertise default route and GP Pool only(you'll need to define import/export rules for now)
  - **AWS**: You have your own Route53 hosted zone

### Step 1: Clone the Repository

First, clone the repository to your local machine:<br />

```bash
git clone https://github.com/echickering/priv_access.git
cd priv_access
```

### Step 2: Install the Package
```bash
python setup.py install
```

### Step 3: Configuration

Configuring `config/config.yml`

After installation, a template configuration file (`config.example.yml`) is automatically copied to `config.yml`. You need to update `config.yml` with your specific settings.

#### AWS Configuration
- **Tags**: Set global tags that will apply to all AWS resources.
- **StackNameVPC**: Define the CloudFormation VPC template stack name.
- **StackNameEC2**: Define the CloudFormation EC2 template stack name.
- **NamePrefix**: Set a prefix for naming AWS resources.
- **Regions**: Specify the AWS regions and their corresponding settings.
  - **availability_zone**: Availability zone subnets will be deployed in.
  - **VPC Cidr**: Define the CIDR block for the VPC.
  - **subnet1_cidr_block**: Set the CIDR block for the untrust subnet.
  - **subnet2_cidr_block**: Set the CIDR block for the trust subnet.
  - **ngfw_ami_id**: Specify the AWS AMI ID for the NGFW in each region.
  - **key_name**: Provide the SSH key name for accessing VMs in each region.
  - **instance_type**: ability to run specific instance type within a AZ/Local Zone as not all regions/zones have same instance type offering
- **EC2 Data**: Specify instance Type and user_data(for bootstrapping.)
  - **user_data**: set appropriate user data. Do not modify anything contained within { } as they are placeholders from EC2 deployment script(and pulled from palo_alto key)
- **palo_alto** Panorama SW_FW_LICENSE plugin specifics
  - **ip_address1 and ip_address2**: Specify the IP addresses of your Primary and Secondary Panorama instances.
  - **auth_key**: Enter the AUTH key for the Panorama SW_FW_LICENSE plugin.
  - **PanoramaTemplate**: Specify the template stack associated with GlobalProtect.
  - **PanoramaDeviceGroup**: Define the device group that your VMs will attach to for policy configuration.
  - **OutsideVirtualRouter**: Name of the VR for handling outside interface
  - **InsideVirtualRouter**: Name of the VR for handling inside interface and tunnel interfaces
  - **UserZoneName**: Zone name for your VPN users
  - **BranchZone**: Zone name for your OnPrem connections
  - **LicenseManage**: Panorama SW_FW_LICENSE Plugin license manager name
- **ngfw** unmanaged panorama NGFW devices
  - **VirtualRouter**: specificy the "LogicalRouter" name
  - **BranchZone**: specificy zone name to your private access
- **vpn** vpn phase1 and phase2 settings
  - **to be updated**: lots to write... to be updated

### Example config.yml
```yaml
aws:
  Tags:
    Project: 'YourProjectName'
    Environment: 'Development'
    Owner: 'YourName'
    AdditionalTag: 'Value'
  StackNameVPC: 'YourStackName'
  StackNameEC2: 'YourStackName'
  hosted_zone_id: "Z06092323432UDOJ7WQIY6A" #AWS Route53 Hosted Zone ID #
  domain: "domain.com" #AWS Domain associated to the Hosted Zone
  portal_fqdn: "portal.domain.com"
  NamePrefix: 'YourResourcePrefix'
  Regions:
    us-east-1:
      vpc_cidr: "10.22.240.0/23"
      key_name: "us-east1"
      ngfw_ami_id: "ami-0bda05a4d1a0eaf08"
      availability_zones:
          us-east-1-chi-2a: #the first AZ should be an AZ, not a local zone, if you are attaching TGW to the first subnet
            az_name: us-east-1-chi-2a #its just easier to do this
            NetworkBorderGroup: us-east-1-chi-2 #just enter the region/local zone
            instance_type: "m6i.xlarge"
            min_ec2_count: 1
            max_ec2_count: 3
            untrust_subnet_cidr: "10.22.240.0/28" #Untrust subnet
            trust_subnet_cidr: "10.22.240.16/28" #Trust subnet
            globalprotect:
              user_pool1: "10.0.0.0/23" #update pool count based on min/max ec2 count. you can list more than max count, but don't list less than max
              user_pool2: "10.0.2.0/23"
              user_pool3: "10.0.4.0/23"
              ebgp_as1: "64600"
              ebgp_as2: "64601"
              ebgp_as3: "64602"
          us-east-1-dfw-2a:
            az_name: us-east-1-dfw-2a #its just easier to do this
            NetworkBorderGroup: us-east-1-dfw-2 #just enter the region/local zone
            instance_type: "m6i.xlarge"
            min_ec2_count: 1
            max_ec2_count: 3
            untrust_subnet_cidr: "10.22.240.32/28" #Untrust subnet
            trust_subnet_cidr: "10.22.240.48/28" #Trust subnet
            globalprotect:
              user_pool1: "10.0.6.0/23" #update pool count based on min/max ec2 count. you can list more than max count, but don't list less than max
              user_pool2: "10.0.8.0/23"
              user_pool3: "10.0.10.0/23"
              ebgp_as1: "64603"
              ebgp_as2: "64604"
              ebgp_as3: "64605"
          us-east-1-atl-1a:
            az_name: us-east-1-atl-1a #its just easier to do this
            NetworkBorderGroup: us-east-1-atl-1 #just enter the region/local zone
            instance_type: "c5d.2xlarge"
            min_ec2_count: 1
            max_ec2_count: 3
            untrust_subnet_cidr: "10.22.241.0/28" #Untrust subnet
            trust_subnet_cidr: "10.22.241.16/28" #Trust subnet
            globalprotect:
              user_pool1: "10.0.160.0/23" #update pool count based on min/max ec2 count. you can list more than max count, but don't list less than max
              user_pool2: "10.0.180.0/23"
              user_pool3: "10.0.200.0/23"
              ebgp_as1: "64606"
              ebgp_as2: "64607"
              ebgp_as3: "64608"              
    us-east-2:
      vpc_cidr: "10.23.240.0/23"
      key_name: "us-east2"
      ngfw_ami_id: "ami-05c242756184e8330"
      availability_zones:
          us-east-2a:
            az_name: us-east-2a
            NetworkBorderGroup: us-east-2
            instance_type: "m6i.xlarge"
            min_ec2_count: 1
            max_ec2_count: 3
            untrust_subnet_cidr: "10.23.240.0/28" #Unrust subnet
            trust_subnet_cidr: "10.23.240.16/28" #Trust subnet
            tgw_id: tgw-0fd363e13bdb37843
            tgw_cidr: "10.1.120.0/24"
            globalprotect:
              user_pool1: "10.0.12.0/23" #update pool count based on min/max ec2 count. you can list more than max count, but don't list less than max
              user_pool2: "10.0.14.0/23"
              user_pool3: "10.0.16.0/23"
              ebgp_as1: "64609"
              ebgp_as2: "64610"
              ebgp_as3: "64611"
    ap-south-1:
      vpc_cidr: "10.24.240.0/23"
      key_name: "ap-south-1"
      ngfw_ami_id: "ami-0e773f202f548fcee"
      availability_zones:
          ap-south-1a:
            az_name: ap-south-1a
            NetworkBorderGroup: ap-south-1
            instance_type: "m5.xlarge"
            min_ec2_count: 1
            max_ec2_count: 3
            untrust_subnet_cidr: "10.24.240.0/28" #Unrust subnet
            trust_subnet_cidr: "10.24.240.16/28" #Trust subnet
            tgw_id: tgw-0fd36234adf324
            tgw_cidr: "10.3.120.0/24"
            globalprotect:
              user_pool1: "10.0.18.0/23" #update pool count based on min/max ec2 count. you can list more than max count, but don't list less than max
              user_pool2: "10.0.20.0/23"
              user_pool3: "10.0.22.0/23"
              ebgp_as1: "64612"
              ebgp_as2: "64613"
              ebgp_as3: "64614"              
        # # Add more regions as needed
  EC2:
    user_data: | # items with {} are variables, pulled from palo_alto:panorama below
      type=dhcp-client
      hostname={NamePrefix}
      auth-key={panorama_auth_key}
      panorama-server={panorama_ip_address1}
      panorama-server-2={panorama_ip_address2}
      tplname={PanoramaTemplate}
      dgname={PanoramaDeviceGroup}
      plugin-op-commands=panorama-licensing-mode-on
      op-command-modes=jumbo-frame,mgmt-interface-swap
      op-cmd-dpdk-pkt-io=on
      vm-series-auto-registration-pin-id=962c24cc-4305-4618-a63a-c33d3346c467
      vm-series-auto-registration-pin-value=312ce80318354d1e8d4472e96f16546a
palo_alto:
  panorama:
    ip_address1: 10.18.236.83
    ip_address2: 10.254.0.238
    auth_key: _AQ__2v6ck2zMRCMQugJDtfDzLeFrPP #sw_fw_license auth key
    PanoramaTemplate: PPA-TPL
    PanoramaTemplateStack: PPA-TPL-Stack
    PanoramaDeviceGroup: PPA-DG
    OutsideVirtualRouter: "PPA-Untrust-VR"
    InsideVirtualRouter: "PPA-Trust-VR"
    UserZoneName: "VPN-Users"
    BranchZone: "Branch"
    LicenseManager: "PrivatePrismaLM" #license manager name used for sw_fw_license plugin in panorama
  ngfw:
    VirtualRouter: default
    BranchZone: "AWS"
vpn:
  crypto_settings:
    ike_crypto: 
      name: "IKE_Crypto"
      auth: "sha512"
      dh_group: "group19"
      encryption: "aes-256-cbc"
    ipsec_crypto: 
      name: "IPSEC_Crypto"
      auth: "none"
      dh_group: "group19"
      encryption: "aes-256-gcm"
    ike_gw: 
      psk: "EnterYourPSKHere$" #PSK Support for now.. will figure a better way to do this eventually
  on_prem_vpn_settings:
    site1:
      ike_peer_ip: "108.44.161.18"
      bgp_peer_ip: "169.254.10.1"
      as_number: "65000"
    site2:
      ike_peer_ip: "108.44.161.20"
      bgp_peer_ip: "169.254.10.2"
      as_number: "65000"
```

### Step 4: Credentials

#### AWS Credentials
***Set the following:***

- **config/aws_credentials.yml**:
  - **access_key_id**: Define access_key_id
  - **secret_access_key**: Define secret_access_key
  - **default_region**: Define default_region.

#### Panorma Credentials
- **config/pan_credential.ymls**:
  - **palo_alto_ngfw_url**: Enter the IP or FQDN of Panorama Appliance.
  - **palo_alto_password**: Enter your API Service Account Password(if desired, if not set API-Key)
  - **palo_alto_username**: Enter your API Service Account Username(if desired, if not set API-Key)
  - **palo_alto_username**: Enter your API KEY (If you don't have it, either obtain your API-Key or enter credentials above)

#### NGFW Credentials
- **config/ngfw_credential.ymls**:
  - **palo_alto_ngfw_url**: Enter the IP or FQDN of Panorama Appliance.
  - **palo_alto_password**: Enter your API Service Account Password(if desired, if not set API-Key)
  - **palo_alto_username**: Enter your API Service Account Username(if desired, if not set API-Key)
  - **palo_alto_username**: Enter your API KEY (If you don't have it, either obtain your API-Key or enter credentials above)