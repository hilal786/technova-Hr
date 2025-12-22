from odoo import models, fields, api
from odoo.exceptions import AccessError


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    office_latitude = fields.Float()
    office_longitude = fields.Float()
    allowed_radius_m = fields.Integer(default=100)

    def write(self, vals):
        restricted_fields = {'office_latitude', 'office_longitude', 'allowed_radius_m'}

        if restricted_fields.intersection(vals.keys()):
            if not self.env.user.has_group('hr.group_hr_manager'):
                raise AccessError(
                    "You are not allowed to modify office attendance location."
                )

        return super().write(vals)