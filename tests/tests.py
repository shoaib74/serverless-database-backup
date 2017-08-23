import unittest
import boto3
import json

from mock import MagicMock, call, ANY

from moto import mock_ec2, mock_sns
from backuplambda import *


def add_volume(tag_name, tag_value, region_name):

    ec2_boto = boto3.client('ec2', region_name=region_name)

    ec2_boto.create_volume(Size=200, AvailabilityZone=region_name+"a")

    vols = ec2_boto.describe_volumes()

    resource_id = vols["Volumes"][0]["VolumeId"]
    ec2_boto.create_tags(Resources=[resource_id],
                         Tags=[{"Key": tag_name, "Value": tag_value}])

    return resource_id


def add_volume_snapshot(resource_id, description, region_name):

    ec2_boto = boto3.client('ec2', region_name=region_name)
    current_snap = ec2_boto.create_snapshot(VolumeId=resource_id,
                                            Description=description)


class EC2BackupManagerTest(unittest.TestCase):

    @mock_ec2
    def test_resolve_resource_bytag(self):

        add_volume("Snapshot", "True", "ap-southeast-1")
        add_volume("Name", "Anotherone", "ap-southeast-1")

        mgr = EC2BackupManager(ec2_region_name="ap-southeast-1",
                               period="day",
                               tag_name="Snapshot",
                               tag_value="True",
                               date_suffix="dd",
                               keep_count="2")

        volumes = mgr.get_backable_resources()

        assert len(volumes) == 1


class RDSBackupManagerTest(unittest.TestCase):

    def test_snapshot_resource_for_standard(self):

        mgr = RDSBackupManager(rds_region_name="ap-southeast-1",
                               period="day",
                               tag_name="Snapshot",
                               tag_value="True",
                               date_suffix="dd",
                               keep_count="2")

        mgr.conn = MagicMock()

        resource = {"DBInstanceIdentifier": "db-1234"}

        description = ""
        tags = {"value1": "value2"}

        mgr.snapshot_resource(resource, description, tags)

        self.assertEqual(mgr.conn.mock_calls, [
            call.create_db_snapshot(DBInstanceIdentifier='db-1234',
                                    DBSnapshotIdentifier=ANY,
                                    Tags=[{'Value': 'value2', 'Key': 'value1'}])
        ])

    def test_snapshot_resource_for_cluster(self):

        mgr = RDSBackupManager(rds_region_name="ap-southeast-1",
                               period="day",
                               tag_name="Snapshot",
                               tag_value="True",
                               date_suffix="dd",
                               keep_count="2")

        mgr.conn = MagicMock()

        resource = {"DBInstanceIdentifier": "db-1234", "DBClusterIdentifier": "cluster-5678"}

        description = ""
        tags = {"value1": "value2"}

        mgr.snapshot_resource(resource, description, tags)

        self.assertEqual(mgr.conn.mock_calls, [
            call.create_db_cluster_snapshot(DBClusterIdentifier='db-1234',
                                            DBClusterSnapshotIdentifier=ANY,
                                            Tags=[{'Value': 'value2', 'Key': 'value1'}])
        ])


class LambdaHandlerTest(unittest.TestCase):

    @mock_ec2
    @mock_sns
    def test_ec2_one_volume(self):

        region_name = "ap-southeast-2"

        add_volume("MakeSnapshot", "True", region_name)
        add_volume("Name", "Anotherone", region_name)

        sns_boto = boto3.client('sns', region_name=region_name)

        response = sns_boto.create_topic(Name="datopic")
        arn = response["TopicArn"]

        event = {
            "period_label": "day",
            "period_format": "%a%H",

            "ec2_region_name": region_name,
            # "rds_region_name": region_name,

            "tag_name": "MakeSnapshot",
            "tag_value": "True",

            "arn": arn,

            "keep_count": 2
        }

        result = lambda_handler(event)
        dajson = json.loads(result)

        self.assertEqual(dajson["metrics"]["total_resources"], 1)
        self.assertEqual(dajson["metrics"]["total_creates"], 1)
        self.assertEqual(dajson["metrics"]["total_deletes"], 0)
        self.assertEqual(dajson["metrics"]["total_errors"], 0)

    @mock_ec2
    @mock_sns
    def test_ec2_image_rotation(self):
        region_name = "ap-southeast-2"

        volume = add_volume("MakeSnapshot", "True", region_name)
        add_volume("Name", "Anotherone", region_name)

        add_volume_snapshot(volume, description="day_snapshot-1", region_name=region_name)
        add_volume_snapshot(volume, description="day_snapshot-2", region_name=region_name)

        sns_boto = boto3.client('sns', region_name=region_name)

        response = sns_boto.create_topic(Name="datopic")
        arn = response["TopicArn"]

        event = {
            "period_label": "day",
            "period_format": "%a%H",

            "ec2_region_name": region_name,
            # "rds_region_name": region_name,

            "tag_name": "MakeSnapshot",
            "tag_value": "True",

            "arn": arn,

            "keep_count": 1
        }

        result = lambda_handler(event)
        dajson = json.loads(result)

        self.assertEqual(dajson["metrics"]["total_resources"], 1)
        self.assertEqual(dajson["metrics"]["total_creates"], 1)
        self.assertEqual(dajson["metrics"]["total_deletes"], 2)
        self.assertEqual(dajson["metrics"]["total_errors"], 0)
