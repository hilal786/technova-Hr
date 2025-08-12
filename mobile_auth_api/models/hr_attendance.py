# -*- coding: utf-8 -*-
from odoo import models, fields

class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    is_break = fields.Boolean(string="Is Break", default=False, help="Indicates if this attendance record is for a break period.")
