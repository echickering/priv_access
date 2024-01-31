## Installation

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
Configuring config.yml
After installation, a template configuration file (config.example.yml) is automatically copied to config.yml. You need to update config.yml with your specific settings.

AWS Configuration<br />
Tags: Set global tags that will apply to all AWS resources.<br />
StackName: Define the CloudFormation template stack name.<br />
NamePrefix: Set a prefix for naming AWS resources.<br />
Regions: Specify the AWS regions and their corresponding settings.<br />
    VPC Cidr: Define the CIDR block for the VPC.<br />
    subnet1_cidr_block: Set the CIDR block for the first subnet.<br />
    subnet2_cidr_block: Set the CIDR block for the second subnet.<br />
    ngfw_ami_id: Specify the AWS AMI ID for the NGFW in each region.<br />
    key_name: Provide the SSH key name for accessing VMs in each region.<br />
Palo Alto Configuration<br />
    ip_address1 and ip_address2: Specify the IP addresses of your Primary and Secondary Panorama instances.<br />
    api_key: Enter the API key for the Panorama instances.<br />
    PanoramaTemplate: Specify the template stack associated with GlobalProtect.<br />
    PanoramaDeviceGroup: Define the device group that your VMs will attach to for policy configuration.<br />