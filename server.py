"""
Google Ads MCP Server
----------------------
Exposes Google Ads account data and campaign management as MCP tools
so Claude can query and act on Google Ads accounts.

Setup:
1. Fill in your credentials in the environment variables (see .env.example)
2. Install dependencies: pip install -r requirements.txt
3. Run locally: python server.py
4. Deploy to a public host (Render/Railway/Fly.io) to get a public URL
5. Add that URL as a Custom Connector in Claude Settings > Connectors
"""

import os
from mcp.server.fastmcp import FastMCP
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

mcp = FastMCP(
    "google-ads-mcp",
    host="0.0.0.0",
    port=int(os.environ.get("PORT", 8000)),
)

def get_client():
    """Builds a Google Ads API client from environment variables."""
    config = {
        "developer_token": os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
        "client_id": os.environ["GOOGLE_ADS_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_ADS_CLIENT_SECRET"],
        "refresh_token": os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
        "use_proto_plus": True,
    }
    # Only needed if the account is under a Manager (MCC) account
    login_customer_id = os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
    if login_customer_id:
        config["login_customer_id"] = login_customer_id
    return GoogleAdsClient.load_from_dict(config)


@mcp.tool()
def list_accessible_accounts() -> str:
    """List all Google Ads accounts accessible with these credentials."""
    client = get_client()
    customer_service = client.get_service("CustomerService")
    try:
        accessible_customers = customer_service.list_accessible_customers()
        resource_names = accessible_customers.resource_names
        ids = [rn.split("/")[-1] for rn in resource_names]
        return "Accessible Customer IDs: " + ", ".join(ids)
    except GoogleAdsException as ex:
        return f"Error: {ex}"


@mcp.tool()
def get_campaigns(customer_id: str) -> str:
    """
    Get all campaigns for a given Google Ads Customer ID.
    customer_id should be digits only, no dashes (e.g. '1234567890').
    """
    client = get_client()
    ga_service = client.get_service("GoogleAdsService")

    query = """
        SELECT
          campaign.id,
          campaign.name,
          campaign.status,
          campaign_budget.amount_micros,
          metrics.clicks,
          metrics.impressions,
          metrics.cost_micros
        FROM campaign
        WHERE segments.date DURING LAST_30_DAYS
        ORDER BY campaign.id
    """

    try:
        response = ga_service.search(customer_id=customer_id, query=query)
        rows = []
        for row in response:
            rows.append(
                f"{row.campaign.name} (ID {row.campaign.id}) | "
                f"Status: {row.campaign.status.name} | "
                f"Clicks: {row.metrics.clicks} | "
                f"Impressions: {row.metrics.impressions} | "
                f"Cost: {row.metrics.cost_micros / 1_000_000:.2f}"
            )
        if not rows:
            return "No campaigns found for the last 30 days."
        return "\n".join(rows)
    except GoogleAdsException as ex:
        return f"Error: {ex}"


@mcp.tool()
def pause_campaign(customer_id: str, campaign_id: str) -> str:
    """
    Pause a specific campaign. customer_id and campaign_id are digits only.
    """
    client = get_client()
    campaign_service = client.get_service("CampaignService")
    campaign_operation = client.get_type("CampaignOperation")

    campaign = campaign_operation.update
    campaign.resource_name = campaign_service.campaign_path(customer_id, campaign_id)
    campaign.status = client.enums.CampaignStatusEnum.PAUSED
    client.copy_from(
        campaign_operation.update_mask,
        client.get_type("FieldMask")(paths=["status"]),
    )

    try:
        response = campaign_service.mutate_campaigns(
            customer_id=customer_id, operations=[campaign_operation]
        )
        return f"Paused campaign: {response.results[0].resource_name}"
    except GoogleAdsException as ex:
        return f"Error: {ex}"


if __name__ == "__main__":
    # Runs the MCP server over Streamable HTTP so it can be hosted remotely
    mcp.run(transport="streamable-http")
