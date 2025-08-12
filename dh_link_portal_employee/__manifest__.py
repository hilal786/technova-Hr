
{
	'name': 'Employee Portal User Link',
	'version': '18.0.0.1',
	'category': 'web',
	'author':'Datahat Solutions LLP',
	'summary': 'This module establishes a direct link between an employee and their corresponding portal user account in Odoo. It ensures better synchronization and access control by associating employee records with portal users, enabling employees to log in via the portal and view or interact with assigned data as per defined access rights.',
	'description': """
		This module establishes a direct link between an employee and their corresponding portal user account in Odoo. It ensures better synchronization and access control by associating employee records with portal users, enabling employees to log in via the portal and view or interact with assigned data as per defined access rights.
		Key Features:
		    Links each employee with a specific portal user.

		    Automatically assigns portal access to the linked user if not already set.

		    Enables employees to view their personal and job-related details via the portal.

		    Enhances communication and transparency between HR and staff.

		    Supports user-friendly interface for HR to manage employee–user relationships.

		Use Case:
			Ideal for organizations that want their employees to securely access personal HR data, leave records, payslips, or assigned tasks through the Odoo portal.
		""",
	'depends': ['base','hr','portal','contacts'],
	'data': [
		'views/hr_employee_view.xml',
	],
	'images': ['static/description/banner.gif'],
	'application': True,
	'license': 'LGPL-3',
}