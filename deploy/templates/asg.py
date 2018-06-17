#!/usr/bin/env python3

# coding: utf-8
from troposphere import Base64, FindInMap, GetAtt, GetAZs
from troposphere import Parameter, Output, Ref, Template, Tags, ImportValue, cloudformation, Join
from troposphere import autoscaling, elasticloadbalancing
from troposphere import cloudwatch
import troposphere.ec2 as ec2
import troposphere.iam as iam
from lib.ec2_adapter import Ec2Adapter
from lib.sts_adapter import StsAdapter
from lib.common_utils import internet


class asgSpotContinuity(object):
    def __init__(self, sceptre_user_data):
        self.sceptre_user_data = sceptre_user_data
        ec2Connection = Ec2Adapter(self.sceptre_user_data["profile"], self.sceptre_user_data["region"])
        stsConnection = StsAdapter(self.sceptre_user_data["profile"], self.sceptre_user_data["region"])
        ip = internet()
        self.VpcId = ec2Connection.get_default_vpc()
        self.amiId = ec2Connection.get_latest_ami()
        self.actualIp = ip.get_actual_ip()
        self.account_id = stsConnection.get_account_id()
        self.keyname = self.sceptre_user_data["keyname"]
        self.instance_type = self.sceptre_user_data["instance_type"]
        self.spot_price = self.sceptre_user_data["spot_price"]
        self.region = self.sceptre_user_data["region"]
        self.service_tag = "web-demo"
        self.subnets = ec2Connection.get_available_subnets(self.VpcId)
        self.Azs = GetAZs("")
        self.add_template()
        self.add_security_group_load_balancer()
        self.add_security_group_instance()
        self.add_launchconfig_ondemand()
        self.add_launchconfig_spot()
        self.add_loadbalancer()
        self.add_autoscaling_ondemand()
        self.add_autoscaling_spot()
        self.add_scaling_policy_spot_up()
        self.add_scaling_policy_spot_down()
        self.add_scaling_policy_ondemand_up()
        self.add_scaling_policy_ondemand_down()
        self.add_cpu_usage_alarm_spot_high()
        self.add_cpu_usage_alarm_spot_low()
        self.add_cpu_credit_balance_spot_low()
        self.add_cpu_usage_alarm_ondemand_high()
        self.add_cpu_usage_alarm_ondemand_low()
        self.add_cpu_credit_balance_ondemand_low()
        self.add_iam_role()
        self.add_loadbalancer_output()


    def add_template(self):
        self.template = Template()
        self.template.add_description(
            "Test autoscaling group"
        )

    def add_security_group_instance(self):
        self.securityGroup = self.template.add_resource(
            ec2.SecurityGroup
            (
                    "SecurityGroup",
                    GroupDescription="Actual IP",
                    VpcId=self.VpcId,
                    SecurityGroupIngress=[
                        ec2.SecurityGroupRule(
                            IpProtocol="tcp",
                            FromPort="22",
                            ToPort="22",
                            CidrIp=self.actualIp + "/32",
                            Description="Actual Ip Address for SSH"
                        ),
                        ec2.SecurityGroupRule(
                            IpProtocol="tcp",
                            FromPort="80",
                            ToPort="80",
                            CidrIp=self.actualIp + "/32",
                            Description="Actual Ip Address for http"
                        ),
                        ec2.SecurityGroupRule(
                            IpProtocol="tcp",
                            FromPort="80",
                            ToPort="80",
                            SourceSecurityGroupId=GetAtt(self.securityGroupLoadBalancer, "GroupId"),
                            Description="Allow Load Balancer"
                        )


                    ],
                    Tags=Tags(
                        Name='SecurityGroup')
            )
        )

    def add_security_group_load_balancer(self):
        self.securityGroupLoadBalancer = self.template.add_resource(
            ec2.SecurityGroup
            (
                "LoadBalancerSecurityGroup",
                GroupDescription="Actual IP",
                VpcId=self.VpcId,
                SecurityGroupIngress=[
                    ec2.SecurityGroupRule(
                        IpProtocol="TCP",
                        FromPort="80",
                        ToPort="80",
                        CidrIp=self.actualIp + "/32",
                        Description="Actual Ip Address"
                    )
                ],
                Tags=Tags(
                    Name='LoadBalancerSecurityGroup')
            )
        )

    def add_iam_role(self):
        self.iam_role = self.template.add_resource(iam.Role(
            "iamRole",
            Path="/",
            AssumeRolePolicyDocument={"Statement": [{
                "Effect": "Allow",
                "Principal": {
                    "Service": ["ec2.amazonaws.com"]
                },
                "Action": ["sts:AssumeRole"]
            }]},
            Policies=[
                iam.Policy(
                    PolicyName="Ec2Access",
                    PolicyDocument={
                        "Statement": [{
                            "Effect": "Allow",
                            "Action": [
                                "ec2:DescribeInstances"
                            ],
                            "Resource": "*"
                        }
                        ],
                    }
                ),
                iam.Policy(
                    PolicyName="DynamoDB",
                    PolicyDocument={
                        "Statement": [{
                            "Effect": "Allow",
                            "Action": "dynamodb:*",
                            "Resource": "arn:aws:dynamodb:" + self.region + ":" + self.account_id + ":table/terminateDB"
                        }
                        ]

                    }

                )
            ]
        )
        )

        self.cfninstanceprofile = self.template.add_resource(iam.InstanceProfile(
            "InstanceProfile",
            Roles=[
                Ref(self.iam_role)
            ]
        ))

    def add_launchconfig_ondemand(self):
        self.launchconfig_ondemand = self.template.add_resource(autoscaling.LaunchConfiguration(
            "LaunchConfigurationOnDemand",
            UserData=Base64(Join('', [
                "#!/bin/bash\n",
                "cfn-signal -e 0",
                "    --resource AutoscalingGroup",
                "    --stack ", Ref("AWS::StackName"),
                "    --region ", Ref("AWS::Region"), "\n",
                "yum -y install docker htop stress && service docker start\n",
                "docker run -d -p 80:8080 stealthizer/docker-aws-info\n"
            ])),
            ImageId=self.amiId,
            KeyName=self.keyname,
            IamInstanceProfile=Ref("InstanceProfile"),
            BlockDeviceMappings=[
                ec2.BlockDeviceMapping(
                    DeviceName="/dev/xvda",
                    Ebs=ec2.EBSBlockDevice(
                        VolumeSize="8"
                    )
                ),
            ],
            SecurityGroups=[Ref(self.securityGroup), Ref(self.securityGroupLoadBalancer)],
            InstanceType=self.instance_type,
        ))

    def add_launchconfig_spot(self):
        self.launchconfig_spot = self.template.add_resource(autoscaling.LaunchConfiguration(
            "LaunchConfigurationOnSpot",
            UserData=Base64(Join('', [
                "#!/bin/bash\n",
                "cfn-signal -e 0",
                "    --resource AutoscalingGroup",
                "    --stack ", Ref("AWS::StackName"),
                "    --region ", Ref("AWS::Region"), "\n",
                "yum -y install docker htop stress && service docker start\n",
                "docker run -d -p 80:8080 stealthizer/docker-aws-info\n"
            ])),
            ImageId=self.amiId,
            KeyName=self.keyname,
            SpotPrice=self.spot_price,
            IamInstanceProfile=Ref("InstanceProfile"),
            BlockDeviceMappings=[
                ec2.BlockDeviceMapping(
                    DeviceName="/dev/xvda",
                    Ebs=ec2.EBSBlockDevice(
                        VolumeSize="8"
                    )
                ),
            ],
            SecurityGroups=[Ref(self.securityGroup), Ref(self.securityGroupLoadBalancer)],
            InstanceType=self.instance_type,
        ))

    def add_loadbalancer(self):
        self.LoadBalancer = self.template.add_resource(elasticloadbalancing.LoadBalancer(
                "LoadBalancer",
                ConnectionDrainingPolicy=elasticloadbalancing.ConnectionDrainingPolicy(
                    Enabled=True,
                    Timeout=120,
                ),
                Subnets=self.subnets,
                HealthCheck=elasticloadbalancing.HealthCheck(
                Target="HTTP:80/",
                HealthyThreshold="2",
                UnhealthyThreshold="2",
                Interval="5",
                Timeout="4",
            ),
            Listeners=[
                elasticloadbalancing.Listener(
                    LoadBalancerPort="80",
                    InstancePort="80",
                    Protocol="TCP",
                    InstanceProtocol="TCP"
                ),
            ],
            CrossZone=True,
            SecurityGroups=[Ref(self.securityGroupLoadBalancer)],
            LoadBalancerName="demo-elb",
            Scheme="internet-facing",
        ))

    def add_autoscaling_ondemand(self):
        self.AutoscalingGroupOnDemand = self.template.add_resource(autoscaling.AutoScalingGroup(
            "AutoscalingGroupOnDemand",
            DesiredCapacity=self.sceptre_user_data["desired_capacity_ondemand"],
            LaunchConfigurationName=Ref(self.launchconfig_ondemand),
            MinSize=self.sceptre_user_data["minimum_capacity_ondemand"],
            MaxSize=self.sceptre_user_data["maximum_capacity_ondemand"],
            VPCZoneIdentifier=self.subnets,
            LoadBalancerNames=[Ref(self.LoadBalancer)],
            AvailabilityZones=GetAZs(""),
            HealthCheckType="ELB",
            HealthCheckGracePeriod=10,
            Tags=[autoscaling.Tag("Name", "web-server-ondemand", True),
                  autoscaling.Tag("service", self.service_tag, True),
                  autoscaling.Tag("lifecycle", "ondemand", True)]
        ))

    def add_autoscaling_spot(self):
        self.AutoscalingGroupSpot = self.template.add_resource(autoscaling.AutoScalingGroup(
            "AutoscalingGroupSpot",
            DesiredCapacity=self.sceptre_user_data["desired_capacity_spot"],
            LaunchConfigurationName=Ref(self.launchconfig_spot),
            MinSize=self.sceptre_user_data["minimum_capacity_spot"],
            MaxSize=self.sceptre_user_data["maximum_capacity_spot"],
            VPCZoneIdentifier=self.subnets,
            LoadBalancerNames=[Ref(self.LoadBalancer)],
            AvailabilityZones=GetAZs(""),
            HealthCheckType="ELB",
            HealthCheckGracePeriod=10,
            MetricsCollection=[],
            Tags=[autoscaling.Tag("Name", "web-server-spot", True),
                  autoscaling.Tag("service", self.service_tag, True),
                  autoscaling.Tag("lifecycle", "spot", True)]
        ))

    def add_scaling_policy_spot_up(self):
        self.scalingPolicySpotUp = self.template.add_resource(autoscaling.ScalingPolicy(
            "CPUUsageScalingPolicySpotUp",
            AdjustmentType="ChangeInCapacity",
            AutoScalingGroupName=Ref(self.AutoscalingGroupSpot),
            Cooldown="1",
            ScalingAdjustment="1"
        ))

    def add_scaling_policy_spot_down(self):
        self.scalingPolicySpotDown = self.template.add_resource(autoscaling.ScalingPolicy(
            "CPUUsageScalingPolicySpotDown",
            AdjustmentType="ChangeInCapacity",
            AutoScalingGroupName=Ref(self.AutoscalingGroupSpot),
            Cooldown="1",
            ScalingAdjustment="-1"
        ))

    def add_scaling_policy_ondemand_up(self):
        self.scalingPolicyOndemandUp = self.template.add_resource(autoscaling.ScalingPolicy(
            "CPUUsageScalingPolicyOndemandUp",
            AdjustmentType="ChangeInCapacity",
            AutoScalingGroupName=Ref(self.AutoscalingGroupOnDemand),
            Cooldown="1",
            ScalingAdjustment="1"
        ))

    def add_scaling_policy_ondemand_down(self):
        self.scalingPolicyOndemandDown = self.template.add_resource(autoscaling.ScalingPolicy(
            "CPUUsageScalingPolicyOndemandDown",
            AdjustmentType="ChangeInCapacity",
            AutoScalingGroupName=Ref(self.AutoscalingGroupOnDemand),
            Cooldown="1",
            ScalingAdjustment="-1"
        ))

    def add_cpu_usage_alarm_spot_high(self):
        self.CPUUsageAlarmHighSpot = self.template.add_resource(cloudwatch.Alarm(
            "CPUUsageAlarmHighSpot",
            AlarmDescription="Alarm if CPUUtilization go above 60%",
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            Dimensions=[
                cloudwatch.MetricDimension(
                    Name="AutoScalingGroupName",
                    Value=Ref(self.AutoscalingGroupSpot)
                ),
            ],
            Statistic="Average",
            Period="300",
            EvaluationPeriods="1",
            Threshold="60",
            ComparisonOperator="GreaterThanOrEqualToThreshold",
            AlarmActions=[Ref(self.scalingPolicySpotUp)]
        ))

    def add_cpu_usage_alarm_spot_low(self):
        self.CPUUsageAlarmLowSpot = self.template.add_resource(cloudwatch.Alarm(
            "CPUUsageAlarmLowSpot",
            AlarmDescription="Alarm if CPUUtilization go below 5%",
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            Dimensions=[
                cloudwatch.MetricDimension(
                    Name="AutoScalingGroupName",
                    Value=Ref(self.AutoscalingGroupSpot)
                ),
            ],
            Statistic="Average",
            Period="300",
            EvaluationPeriods="2",
            Threshold="5",
            ComparisonOperator="LessThanThreshold",
            AlarmActions=[Ref(self.scalingPolicySpotDown)]
        ))

    def add_cpu_credit_balance_spot_low(self):
        self.CPUCreditAlarmLowSpot = self.template.add_resource(cloudwatch.Alarm(
            "CPUCreditAlarmLowSpot",
            AlarmDescription="Alarm if CPU Credits go below 10",
            Namespace="AWS/EC2",
            MetricName="CPUCreditBalance",
            Dimensions=[
                cloudwatch.MetricDimension(
                    Name="AutoScalingGroupName",
                    Value=Ref(self.AutoscalingGroupSpot)
                ),
            ],
            Statistic="Average",
            Period="60",
            EvaluationPeriods="5",
            Threshold="10",
            ComparisonOperator="LessThanThreshold",
            AlarmActions=[Ref(self.scalingPolicySpotUp)]
        ))

    def add_cpu_usage_alarm_ondemand_high(self):
        self.CPUUsageAlarmHighOndemand = self.template.add_resource(cloudwatch.Alarm(
            "CPUUsageAlarmHighOndemand",
            AlarmDescription="Alarm if CPUUtilization go above 60%",
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            Dimensions=[
                cloudwatch.MetricDimension(
                    Name="AutoScalingGroupName",
                    Value=Ref(self.AutoscalingGroupOnDemand)
                ),
            ],
            Statistic="Average",
            Period="300",
            EvaluationPeriods="2",
            Threshold="60",
            ComparisonOperator="GreaterThanOrEqualToThreshold",
            AlarmActions=[Ref(self.scalingPolicyOndemandUp)]
        ))

    def add_cpu_usage_alarm_ondemand_low(self):
        self.CPUUsageAlarmLowOndemand = self.template.add_resource(cloudwatch.Alarm(
            "CPUUsageAlarmLowOndemand",
            AlarmDescription="Alarm if CPUUtilization go below 5%",
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            Dimensions=[
                cloudwatch.MetricDimension(
                    Name="AutoScalingGroupName",
                    Value=Ref(self.AutoscalingGroupOnDemand)
                ),
            ],
            Statistic="Average",
            Period="300",
            EvaluationPeriods="1",
            Threshold="5",
            ComparisonOperator="LessThanThreshold",
            AlarmActions=[Ref(self.scalingPolicyOndemandDown)]
        ))

    def add_cpu_credit_balance_ondemand_low(self):
        self.CPUCreditAlarmLowOndemand = self.template.add_resource(cloudwatch.Alarm(
            "CPUCreditAlarmLowOndemand",
            AlarmDescription="Alarm if CPU Credits go below 10",
            Namespace="AWS/EC2",
            MetricName="CPUCreditBalance",
            Dimensions=[
                cloudwatch.MetricDimension(
                    Name="AutoScalingGroupName",
                    Value=Ref(self.AutoscalingGroupOnDemand)
                ),
            ],
            Statistic="Average",
            Period="60",
            EvaluationPeriods="10",
            Threshold="10",
            ComparisonOperator="LessThanThreshold",
            AlarmActions=[Ref(self.scalingPolicyOndemandUp)]
        ))

    def add_loadbalancer_output(self):
        self.LoadbalancerDnsOutput = self.template.add_output(Output(
            "LoadBalancerDNSName",
            Description="DNSName of the LoadBalancer",
            Value=Join("", ["http://", GetAtt(self.LoadBalancer, "DNSName")])
        ))

def sceptre_handler(sceptre_user_data):
    sceptre = asgSpotContinuity(sceptre_user_data)
    return sceptre.template.to_json()