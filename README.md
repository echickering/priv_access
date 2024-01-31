#### Welcome
- **Purpose** This project purpose is to create your own GlobalProtect automated solution on AWS(currently)
- **Assumptions** You have a Panorama, a Template and Template Stack with All Network and GlobalProtect settings set with Variables, Certificates Set on Template

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

Configuring `config.yml`

After installation, a template configuration file (`config.example.yml`) is automatically copied to `config.yml`. You need to update `config.yml` with your specific settings.

#### AWS Configuration
- **Tags**: Set global tags that will apply to all AWS resources.
- **StackName**: Define the CloudFormation template stack name.
- **NamePrefix**: Set a prefix for naming AWS resources.
- **Regions**: Specify the AWS regions and their corresponding settings.
  - **VPC Cidr**: Define the CIDR block for the VPC.
  - **subnet1_cidr_block**: Set the CIDR block for the untrust subnet.
  - **subnet2_cidr_block**: Set the CIDR block for the trust subnet.
  - **ngfw_ami_id**: Specify the AWS AMI ID for the NGFW in each region.
  - **key_name**: Provide the SSH key name for accessing VMs in each region.

#### Palo Alto Configuration
- **ip_address1 and ip_address2**: Specify the IP addresses of your Primary and Secondary Panorama instances.
- **api_key**: Enter the AUTH key for the Panorama SW_FW_LICENSE plugin.
- **PanoramaTemplate**: Specify the template stack associated with GlobalProtect.
- **PanoramaDeviceGroup**: Define the device group that your VMs will attach to for policy configuration.

### Example config.yml
```yaml
aws:
  Tags:
    Project: 'YourProjectName'
    Environment: 'Development'
    Owner: 'YourName'
    AdditionalTag: 'Value'
  StackName: 'YourStackName'
  NamePrefix: 'YourResourcePrefix'
  Regions:
    us-west-2:
      vpc_cidr: '10.0.0.0/16'
      subnet1_cidr_block: '10.0.1.0/24'
      subnet2_cidr_block: '10.0.2.0/24'
      ngfw_ami_id: 'ami-xxxxxxx'
      key_name: 'your-ssh-key' #Without the .pem
palo_alto:
  ip_address1: '192.0.2.1'
  ip_address2: '192.0.2.2'
  api_key: 'your-auth-key' #AUTH key for the Panorama SW_FW_LICENSE plugin.
  PanoramaTemplate: 'YourTemplateStack'
  PanoramaDeviceGroup: 'YourDeviceGroup'
```

### Step 4: Credentials

#### AWS Credentials
- **aws_credentials**: In config/aws_credentials set:
  - **access_key_id**: Define the CloudFormation template stack name.
  - **secret_access_key**: Set a prefix for naming AWS resources.
  - **default_region**: Specify the AWS regions and their corresponding settings.

#### Panorma Credentials
- **pan_credentials**: In config/pan_credentials set:
  - **palo_alto_ngfw_url**: Enter the IP or FQDN of Panorama Appliance.
  - **palo_alto_password**: Enter your API Service Account Password(if desired, if not set API-Key)
  - **palo_alto_username**: Enter your API Service Account Username(if desired, if not set API-Key)
  - **palo_alto_username**: Enter your API KEY (If you don't have it, either obtain your API-Key or enter credentials above)