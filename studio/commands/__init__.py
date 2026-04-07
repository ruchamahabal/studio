import click
import frappe
from frappe.commands import get_site, pass_context


@click.command("build-studio-app")
@click.argument("app_name")
@click.option("--site", help="site name")
@pass_context
def build_studio_app(context, app_name: str, site: str | None = None):
	"""Build a single studio app (reads from DB, needs site)."""
	if not site:
		site = get_site(context)

	frappe.init(site)
	frappe.connect()
	app = frappe.get_doc("Studio App", app_name)
	app.generate_app_build()
	print(f"Studio App '{app_name}' built successfully.")


@click.command("build-custom-studio-apps")
@click.option("--site", help="site name")
@pass_context
def build_custom_studio_apps(context, site: str | None = None):
	"""Build all custom (non-standard) studio apps for a site."""
	if not site:
		site = get_site(context)

	frappe.init(site)
	frappe.connect()
	apps = frappe.get_all("Studio App", filters={"is_standard": 0, "published": 1}, pluck="name")

	if not apps:
		print("No custom studio apps found.")
		return

	for app_name in apps:
		app = frappe.get_doc("Studio App", app_name)
		try:
			app.generate_app_build()
			print(f"✓ Built {app_name}")
		except Exception as e:
			print(f"✗ Failed to build {app_name}: {e}")


@click.command("build-standard-studio-apps")
def build_standard_studio_apps():
	"""Build all standard (exported) studio apps from disk. No site needed."""
	from frappe.build import get_node_env
	from frappe.commands import popen

	studio_app_path = frappe.get_app_source_path("studio")
	popen("yarn build-standard-apps", cwd=studio_app_path, env=get_node_env(), raise_err=True)


commands = [
	build_studio_app,
	build_custom_studio_apps,
	build_standard_studio_apps,
]
