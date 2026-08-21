from boto3.session import Session

from runacross import Account, map_account_regions


def list_instance_ids(session: Session, _account: Account, _region: str) -> list[str]:
    ec2 = session.client("ec2")
    instance_ids: list[str] = []

    for page in ec2.get_paginator("describe_instances").paginate():
        for reservation in page["Reservations"]:
            instance_ids.extend(
                instance["InstanceId"] for instance in reservation["Instances"]
            )

    return instance_ids


def main() -> None:
    results = map_account_regions(
        list_instance_ids,
        accounts=[
            "111111111111",
            "222222222222",
        ],
        regions=["eu-west-1", "us-east-1"],
        role_name="SecurityAuditRole",
    )

    for result in results:
        if result.success:
            print(f"{result.account.id} {result.region}: {result.value}")
        else:
            print(
                f"{result.account.id} {result.region}: {result.phase}: {result.error}"
            )


if __name__ == "__main__":
    main()
