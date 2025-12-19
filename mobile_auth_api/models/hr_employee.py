from odoo import models, fields, api


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    office_latitude = fields.Float()
    office_longitude = fields.Float()
    allowed_radius_m = fields.Integer(default=100)
