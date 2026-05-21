import odoo
from odoo import http, SUPERUSER_ID, fields
from odoo.http import request, Response
from odoo.addons.web.controllers.utils import ensure_db
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta
import json
import logging
import base64
import math
import re
import pytz
from datetime import time
from datetime import datetime
from odoo.exceptions import ValidationError, UserError

class MobileApiHome(http.Controller):

    def _get_user_day_range_utc(self):
        user = request.env.user
        tz_name = user.tz or 'UTC'
        user_tz = pytz.timezone(tz_name)

        now_user = datetime.now(user_tz)
        today_user = now_user.date()

        start_user = user_tz.localize(datetime.combine(today_user, time.min))
        end_user = user_tz.localize(datetime.combine(today_user, time.max))

        return (
            start_user.astimezone(pytz.utc),
            end_user.astimezone(pytz.utc),
            today_user
        )

    def get_image_url(self, model, id, field):
        base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return base_url + '/web/image?' + 'model=' + model + '&id=' + str(id) + '&field=' + field

    @http.route('/get-countries', type='http', auth='none', methods=['GET'])
    def get_countries(self, **kw):
        countries = request.env['res.country'].with_user(SUPERUSER_ID).search_read([], ['name', 'code'])
        return Response(json.dumps({"status": 200, "countries": countries}, ensure_ascii=False),
                        content_type="application/json", status=200)

    @http.route('/get-states', type='http', auth='none', methods=['GET', 'POST'], csrf=False)
    def get_states(self, **kw):
        country_code = 'CH'
        kw = request.get_json_data()
        if kw.get('country_code', False):
            country_code = kw.get('country_code')
        states = request.env['res.country.state'].with_user(SUPERUSER_ID).search_read(
            [('country_id.code', '=', country_code)], ['name', 'code'])
        return Response(json.dumps({"status": 200, "states": states}, ensure_ascii=False),
                        content_type="application/json", status=200)
    
    @http.route('/mobile/login', type='json', auth='none', readonly=False)
    def mobile_login(self, **kw):
        ensure_db()

        data = request.get_json_data() or {}
        login = data.get("login")
        password = data.get("password")

        if not login or not password:
            return {"status": 400, "error": "Missing login or password"}

        request.session.logout()

        if request.httprequest.method == 'POST' and request.session.uid:
            user = request.env['res.users'].browse(request.session.uid)

            employee = request.env['hr.employee'].sudo().search(
                [('user_id', '=', user.id)], limit=1
            )

            return {
                "status": 200,
                "uid": request.session.uid,
                "db": request.session.db,
                "username": request.session.login,
                "auth_info": "Already Logged in",

                "name": user.name or "",
                "street": user.partner_id.street or "",
                "city": user.partner_id.city or "",
                "zip": user.partner_id.zip or "",
                "country_id": user.partner_id.country_id.code if user.partner_id.country_id else "",
                "state_id": user.partner_id.state_id.code if user.partner_id.state_id else "",

                "job_title": employee.job_title if employee else "",
                "birthday": employee.birthday.strftime('%d.%m.%Y') if employee and employee.birthday else "",
                "number": employee.private_phone if employee else "",
                "manager": employee.parent_id.name if employee and employee.parent_id else "",

                "profile_image_url": self.get_image_url(
                    'res.users', user.id, 'image_1920'
                ) or "",
            }

        try:
            credential = {
                key: value for key, value in data.items()
                if key in ['login', 'password', 'type'] and value
            }
            credential.setdefault('type', 'password')

            auth_info = request.session.authenticate(request.db, credential)
            request.params['login_success'] = True

            user = request.env.user
            employee = request.env['hr.employee'].sudo().search(
                [('user_id', '=', user.id)], limit=1
            )

            return {
                "status": 200,
                "uid": request.session.uid,
                "db": request.session.db,
                "username": request.session.login,
                "auth_info": auth_info,

                "name": user.name or "",
                "street": user.partner_id.street or "",
                "city": user.partner_id.city or "",
                "zip": user.partner_id.zip or "",
                "country_id": user.partner_id.country_id.code if user.partner_id.country_id else "",
                "state_id": user.partner_id.state_id.code if user.partner_id.state_id else "",

                "job_title": employee.job_title if employee else "",
                "birthday": employee.birthday.strftime('%d.%m.%Y') if employee and employee.birthday else "",
                "number": employee.private_phone if employee else "",
                "manager": employee.parent_id.name if employee and employee.parent_id else "",

                "profile_image_url": self.get_image_url(
                    'res.users', user.id, 'image_1920'
                ) or "",
                "image_1920": user.image_1920 or "",
            }

        except odoo.exceptions.AccessDenied as e:
            if e.args == odoo.exceptions.AccessDenied().args:
                return {
                    "status": 401,
                    "error": "Wrong login/password"
                }
            else:
                return {
                    "status": 400,
                    "error": e.args[0]
                }



    def _get_default_expense_product(self):
        product = request.env['product.product'].sudo().search(
            [('can_be_expensed', '=', True)],
            limit=1
        )
        return product

    @http.route('/mobile/expenses', type='http', auth='user', methods=['POST'], csrf=False)
    def create_expense(self, **kwargs):

        user = request.env.user

        employee = request.env['hr.employee'].sudo().search(
            [('user_id', '=', user.id)],
            limit=1
        )

        if not employee:
            return request.make_json_response({
                "status": 400,
                "error": "No employee linked to this user"
            })

        reason = kwargs.get('reason')
        date = kwargs.get('date')
        amount = kwargs.get('amount') or 0
        product_id = kwargs.get('product_id')

        if not reason or not date:
            return request.make_json_response({
                "status": 400,
                "error": "reason and date are required"
            })

        if not product_id:
            product = self._get_default_expense_product()
            product_id = product.id if product else False

        if not product_id:
            return request.make_json_response({
                "status": 400,
                "error": "No expense product found"
            })

        expense = request.env['hr.expense'].sudo().create({
            'name': reason,
            'employee_id': employee.id,
            'product_id': int(product_id),
            'total_amount': float(amount),
            'date': date,
            'quantity': 1.0,
            'payment_mode': 'own_account',
        })

        uploaded_file = request.httprequest.files.get('attachment')

        attachment_uploaded = False
        attachment_name = False

        if uploaded_file:

            allowed_types = [
                'image/jpeg',
                'image/png',
                'application/pdf'
            ]

            if uploaded_file.content_type not in allowed_types:
                return request.make_json_response({
                    "status": 400,
                    "error": "Only JPG, PNG and PDF files are allowed"
                })

            uploaded_file.seek(0, 2)
            file_size = uploaded_file.tell()
            uploaded_file.seek(0)

            max_size = 10 * 1024 * 1024  # 10 MB

            if file_size > max_size:
                return request.make_json_response({
                    "status": 400,
                    "error": "File size exceeds 10 MB limit"
                })

            file_content = uploaded_file.read()

            request.env['ir.attachment'].sudo().create({
                'name': uploaded_file.filename,
                'datas': base64.b64encode(file_content),
                'res_model': 'hr.expense',
                'res_id': expense.id,
                'mimetype': uploaded_file.content_type,
                'type': 'binary',
            })

            attachment_uploaded = True
            attachment_name = uploaded_file.filename

        return request.make_json_response({
            "status": 200,
            "message": "Expense created successfully",
            "expense_id": expense.id,
            "attachment_uploaded": attachment_uploaded,
            "attachment_name": attachment_name
        })

    @http.route('/mobile/expenses/list', type='json', auth='user', methods=['POST'], csrf=False)
    def list_expenses(self, **kwargs):
        user = request.env.user
        employee = request.env['hr.employee'].sudo().search(
            [('user_id', '=', user.id)], limit=1
        )

        if not employee:
            return {"status": 400, "error": "No employee linked to this user"}

        data = request.get_json_data() or {}

        page = int(data.get('page', 1))
        limit = int(data.get('limit', 10))
        offset = (page - 1) * limit

        domain = [('employee_id', '=', employee.id)]

        total = request.env['hr.expense'].sudo().search_count(domain)
        total_pages = (total + limit - 1) // limit if limit else 1

        expenses = request.env['hr.expense'].sudo().search(
            domain,
            offset=offset,
            limit=limit,
            order="date desc"
        )

        result = []
        for exp in expenses:
            attachments = request.env['ir.attachment'].sudo().search([
                ('res_model', '=', 'hr.expense'),
                ('res_id', '=', exp.id)
            ], limit=1)

            attachment_data = {}

            base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url')

            if attachments:
                attachment_data = {
                    "attachment_id": attachments.id,
                    "attachment_name": attachments.name,
                    "attachment_mimetype": attachments.mimetype,
                    "preview_url": f"{base_url}/web/content/{attachments.id}",
                    "download_url": f"{base_url}/web/content/{attachments.id}?download=true",
                }

            result.append({
                'id': exp.id,
                'name': exp.name,
                'amount': exp.total_amount,
                'state': exp.state,
                'date': str(exp.date),

                'employee': exp.employee_id.name,
                'category': exp.product_id.categ_id.name if exp.product_id.categ_id else "",
                'product': exp.product_id.name,

                'payment_mode': dict(
                    exp._fields['payment_mode'].selection
                ).get(exp.payment_mode),

                'company': exp.company_id.name if exp.company_id else "",

                'has_attachment': bool(attachments),

                'attachment': attachment_data
            })
        return {
            "status": 200,
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": total_pages,
            "expenses": result
        }


    @http.route('/mobile/leaves/list', type='json', auth='user', methods=['POST'], csrf=False)
    def list_leaves(self, **kwargs):
        data = request.get_json_data()
        user = request.env.user
        domain = []

        if not user.has_group('base.group_system'):
            employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
            if not employee:
                return {"status": 400, "error": "No employee linked to this user"}
            domain.append(('employee_id', '=', employee.id))
        else:
            employee_id = data.get('employee_id')
            if employee_id:
                domain.append(('employee_id', '=', int(employee_id)))

        page = int(data.get('page', 1))
        limit = int(data.get('limit', 10))
        offset = (page - 1) * limit
        search = data.get('search', '')

        if search:
            domain += ['|', ('name', 'ilike', search), ('holiday_status_id.name', 'ilike', search)]

        Leave = request.env['hr.leave'].sudo()
        total = Leave.search_count(domain)
        total_pages = (total + limit - 1) // limit if limit else 1

        leaves = Leave.search(domain, offset=offset, limit=limit, order="request_date_from desc")

        approved_count = Leave.search_count(domain + [('state', '=', 'validate')])
        new_leave_count = Leave.search_count(domain + [('state', 'in', ['validate1', 'confirm'])])

        results = []
        for leave in leaves:
            results.append({
                "id": leave.id,
                "employee_name": leave.employee_id.name,
                "department": leave.employee_id.department_id.name or "",
                "job_title": leave.employee_id.job_title or "",
                "leave_type": leave.holiday_status_id.name,
                "period": f"{leave.request_date_from} to {leave.request_date_to}",
                "reason": leave.name,
                "status": leave.state,
                'profile_image_url': self.get_image_url('hr.employee', leave.employee_id.id, 'image_1920') or "",
                'image_1920': leave.employee_id.image_1920 or "" ,
            })

        return {
            "status": 200,
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": total_pages,
            "approved_count": approved_count,
            "new_leave_count": new_leave_count,
            "leaves": results
        }

    @http.route('/mobile/leaves/types', type='http', auth='user', methods=['GET'], csrf=False)
    def get_available_leave_types(self):
        user = request.env.user

        employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        if not employee:
            return {"status": 400, "error": "No employee linked to this user"}

        allocated_types = request.env['hr.leave.allocation'].sudo().search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'validate')
        ]).mapped('holiday_status_id.id')

        all_types = request.env['hr.leave.type'].sudo().search([]).mapped('id')

        all_type_ids = list(set(allocated_types + all_types))

        leave_types = request.env['hr.leave.type'].sudo().browse(all_type_ids).read(['id', 'name'])

        data = {
            "status": 200,
            "leave_types": leave_types
        }
        return Response(json.dumps(data), content_type='application/json')

    @http.route('/mobile/leaves/create', type='json', auth='user', methods=['POST'], csrf=False)
    def create_leave(self, **kwargs):

        user = request.env.user

        employee = request.env['hr.employee'].sudo().search(
            [('user_id', '=', user.id)],
            limit=1
        )

        if not employee:
            return {
                "status": 400,
                "error": "No employee linked to this user"
            }

        data = request.get_json_data() or {}

        leave_type_id = data.get('leave_type_id')
        date_from = data.get('date_from')
        date_to = data.get('date_to')
        reason = data.get('reason')

        if not all([leave_type_id, date_from, date_to, reason]):
            return {
                "status": 400,
                "error": "Missing required fields"
            }

        try:

            leave_type = request.env['hr.leave.type'].sudo().browse(
                int(leave_type_id)
            )

            if not leave_type.exists():
                return {
                    "status": 400,
                    "error": "Invalid leave type"
                }

            # =====================================================
            # FULL DAY LEAVE
            # =====================================================

            if leave_type.request_unit == 'day':

                request_date_from = fields.Date.to_date(date_from)
                request_date_to = fields.Date.to_date(date_to)

                if request_date_to < request_date_from:
                    return {
                        "status": 400,
                        "error": "date_to must be greater than or equal to date_from"
                    }

                # =====================================================
                # CHECK LEAVE BALANCE
                # =====================================================

                if leave_type.requires_allocation == 'yes':

                    remaining_leaves = leave_type.with_context(
                        employee_id=employee.id
                    ).virtual_remaining_leaves

                    requested_days = (
                        request_date_to - request_date_from
                    ).days + 1

                    if remaining_leaves < requested_days:
                        return {
                            "status": 400,
                            "error": (
                                f"Insufficient leave balance. "
                                f"Available: {remaining_leaves} days"
                            )
                        }

                # =====================================================
                # CHECK OVERLAPPING LEAVES
                # =====================================================

                existing_leave = request.env['hr.leave'].sudo().search([
                    ('employee_id', '=', employee.id),
                    ('state', '!=', 'cancel'),
                    ('request_date_from', '<=', request_date_to),
                    ('request_date_to', '>=', request_date_from),
                ], limit=1)

                if existing_leave:
                    return {
                        "status": 400,
                        "error": (
                            f"Leave already exists from "
                            f"{existing_leave.request_date_from} to "
                            f"{existing_leave.request_date_to}"
                        )
                    }

                # =====================================================
                # CREATE FULL DAY LEAVE
                # =====================================================

                leave = request.env['hr.leave'].sudo().create({
                    'name': reason,
                    'employee_id': employee.id,
                    'holiday_status_id': int(leave_type_id),

                    'request_date_from': request_date_from,
                    'request_date_to': request_date_to,
                })

            # =====================================================
            # HOURLY LEAVE
            # =====================================================

            else:

                date_from_dt = fields.Datetime.to_datetime(date_from)
                date_to_dt = fields.Datetime.to_datetime(date_to)

                if date_to_dt <= date_from_dt:
                    return {
                        "status": 400,
                        "error": "date_to must be greater than date_from"
                    }

                # =====================================================
                # CHECK OVERLAPPING HOURLY LEAVES
                # =====================================================

                existing_leave = request.env['hr.leave'].sudo().search([
                    ('employee_id', '=', employee.id),
                    ('state', '!=', 'cancel'),
                    ('date_from', '<=', date_to_dt),
                    ('date_to', '>=', date_from_dt),
                ], limit=1)

                if existing_leave:
                    return {
                        "status": 400,
                        "error": (
                            f"Leave already exists from "
                            f"{existing_leave.date_from} to "
                            f"{existing_leave.date_to}"
                        )
                    }

                # =====================================================
                # CREATE HOURLY LEAVE
                # =====================================================

                leave = request.env['hr.leave'].sudo().create({
                    'name': reason,
                    'employee_id': employee.id,
                    'holiday_status_id': int(leave_type_id),

                    'date_from': date_from_dt,
                    'date_to': date_to_dt,

                    'request_date_from': date_from_dt.date(),
                    'request_date_to': date_to_dt.date(),

                    'request_unit_hours': True,

                    'request_hour_from': (
                        date_from_dt.hour +
                        (date_from_dt.minute / 60.0)
                    ),

                    'request_hour_to': (
                        date_to_dt.hour +
                        (date_to_dt.minute / 60.0)
                    ),
                })

            # =====================================================
            # SUCCESS RESPONSE
            # =====================================================

            return {
                "status": 200,
                "message": "Leave request submitted successfully",
                "leave_id": leave.id,
                "leave_type_id": leave.holiday_status_id.id,
                "leave_type": leave.holiday_status_id.name,
                "date_from": str(leave.date_from),
                "date_to": str(leave.date_to),
                "number_of_days": leave.number_of_days,
                "state": leave.state,
            }

        except (ValidationError, UserError) as e:
            return {
                "status": 400,
                "error": str(e)
            }

        except Exception as e:
            return {
                "status": 500,
                "error": str(e)
            }
    @http.route('/mobile/employee/profile', type='json', auth='user', csrf=False)
    def employee_profile(self, **kwargs):
        user = request.env.user
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        if not employee:
            return {"status": 400, "error": "No employee linked to this user"}

        today = fields.Date.today()
        start_week = today - timedelta(days=today.weekday())
        end_week = start_week + timedelta(days=6)

        domain = [('employee_id', '=', employee.id), ('check_in', '>=', start_week), ('check_out', '<=', end_week)]
        attendances = request.env['hr.attendance'].sudo().search(domain)

        attendance_summary = {
            "present": 0,
            "absent": 0,
            "week_off": 0,
            "half_day": 0,
            "leave": 0,
            "holiday": 0,
        }

        calendar = employee.resource_calendar_id or employee.company_id.resource_calendar_id

        holidays = request.env['resource.calendar.leaves'].sudo().search([
            ('calendar_id', '=', calendar.id),
            ('date_from', '<=', end_week),
            ('date_to', '>=', start_week)
        ])

        leaves = request.env['hr.leave'].sudo().search([
            ('employee_id', '=', employee.id),
            ('request_date_from', '<=', end_week),
            ('request_date_to', '>=', start_week),
            ('state', 'in', ['validate'])
        ])

        week_days = [start_week + timedelta(days=i) for i in range(7)]
        for day in week_days:
            day_att = [a for a in attendances if a.check_in.date() == day]
            if day_att:
                worked_hours = sum(
                    [(a.check_out - a.check_in).total_seconds() / 3600 for a in day_att if a.check_out])
                if worked_hours < 4:
                    attendance_summary["half_day"] += 1
                else:
                    attendance_summary["present"] += 1
            elif any(h.date_from.date() <= day <= h.date_to.date() for h in holidays):
                attendance_summary["holiday"] += 1
            elif any(l.request_date_from <= day <= l.request_date_to for l in leaves):
                attendance_summary["leave"] += 1
            elif not calendar.attendance_ids.filtered(lambda a: a.dayofweek == str(day.weekday())):
                attendance_summary["week_off"] += 1
            else:
                attendance_summary["absent"] += 1

        timesheets = request.env['account.analytic.line'].sudo().search_read([
            ('user_id', '=', employee.user_id.id),
            ('date', '=', today)
        ], ['unit_amount'])

        timesheet_hours = sum(t['unit_amount'] for t in timesheets)


        chart_data = []
        for i in range(7):
            day = today - timedelta(days=i)
            daily_timesheets = request.env['account.analytic.line'].sudo().search_read([
                ('user_id', '=', employee.user_id.id),
                ('date', '=', day)
            ], ['unit_amount'])

            total_hours = sum(t['unit_amount'] for t in daily_timesheets)
            chart_data.append({
                "date": str(day),
                "hours": round(total_hours, 2)
            })


        chart_data = sorted(chart_data, key=lambda x: x['date'])

        return {
            "status": 200,
            "employee": {
                "name": employee.name,
                "job_title": employee.job_title,
            },
            "timesheet_summary": {
                "today_hours": round(timesheet_hours, 2),
                "weekly_bar_chart": chart_data,
            },
            "attendance_summary": attendance_summary,
            "profile_image_url": self.get_image_url('hr.employee', employee.id, 'image_1920') or "",
            'image_1920': employee.image_1920 or "" ,
        }

    def _format_duration(self, total_seconds):
        total_seconds = int(total_seconds)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"

    @http.route('/mobile/attendance/logs', type='json', auth='user', csrf=False)
    def mobile_attendance_log(self, **kwargs):
        user = request.env.user
        user_ctx = user.with_context(tz=user.tz)
        tz_name = user.tz or 'UTC'
        user_tz = pytz.timezone(tz_name)

        employee = request.env['hr.employee'].sudo().search(
            [('user_id', '=', user.id)], limit=1
        )
        if not employee:
            return {"status": 400, "error": "Employee not found for user."}

        today_start, today_end, today_user = self._get_user_day_range_utc()
        Attendance = request.env['hr.attendance'].sudo()

        # All today's attendance records
        attendances = Attendance.search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', today_start),
            ('check_in', '<=', today_end)
        ], order='check_in asc')

        # --- Current open sessions ---
        open_work = Attendance.search([
            ('employee_id', '=', employee.id),
            ('check_out', '=', False),
            ('is_break', '=', False)
        ], order='check_in desc', limit=1)

        open_break = Attendance.search([
            ('employee_id', '=', employee.id),
            ('check_out', '=', False),
            ('is_break', '=', True)
        ], order='check_in desc', limit=1)

        # --- Determine current status ---
        if open_break:
            current_status = 'on_break'
        elif open_work:
            current_status = 'checked_in'
        else:
            any_work_today = any(not a.is_break for a in attendances)
            current_status = 'checked_out' if any_work_today else 'not_checked_in'

        # --- Calculate total worked seconds (completed sessions only) ---
        total_worked_seconds = 0
        for att in attendances:
            if not att.is_break and att.check_out:
                delta = (att.check_out - att.check_in).total_seconds()
                total_worked_seconds += max(delta, 0)

        # --- Calculate total break seconds (completed sessions only) ---
        total_break_seconds = 0
        for att in attendances:
            if att.is_break and att.check_out:
                delta = (att.check_out - att.check_in).total_seconds()
                total_break_seconds += max(delta, 0)

        # --- ISO timestamps for mobile real-time timers ---
        check_in_iso = None
        break_start_iso = None

        if open_work:
            check_in_iso = fields.Datetime.context_timestamp(
                user_ctx, open_work.check_in
            ).isoformat()

        if open_break:
            break_start_iso = fields.Datetime.context_timestamp(
                user_ctx, open_break.check_in
            ).isoformat()

        # --- Human-readable time logs ---
        clock_in_display = None
        clock_out_display = None
        break_start_display = None
        break_end_display = None

        work_sessions = [a for a in attendances if not a.is_break]
        break_sessions = [a for a in attendances if a.is_break]

        if work_sessions:
            first_work = work_sessions[0]
            clock_in_display = fields.Datetime.context_timestamp(
                user_ctx, first_work.check_in
            ).strftime("%I:%M:%S %p")

            # Only show clock_out when truly checked out for the day
            if current_status == 'checked_out':
                closed_work = [a for a in work_sessions if a.check_out]
                if closed_work:
                    clock_out_display = fields.Datetime.context_timestamp(
                        user_ctx, max(a.check_out for a in closed_work)
                    ).strftime("%I:%M:%S %p")

        if break_sessions:
            latest_break = max(break_sessions, key=lambda a: a.check_in)
            break_start_display = fields.Datetime.context_timestamp(
                user_ctx, latest_break.check_in
            ).strftime("%I:%M:%S %p")

            if latest_break.check_out:
                break_end_display = fields.Datetime.context_timestamp(
                    user_ctx, latest_break.check_out
                ).strftime("%I:%M:%S %p")

        # --- Office location ---
        office_info = {}
        if employee.office_latitude and employee.office_longitude:
            office_info = {
                "latitude": employee.office_latitude,
                "longitude": employee.office_longitude,
                "allowed_radius_m": employee.allowed_radius_m or 100
            }

        # --- Details card ---
        work_sessions_count = len(work_sessions)
        break_sessions_count = len(break_sessions)

        # Expected hours from employee work schedule
        expected_seconds = 0
        if employee.resource_calendar_id:
            today_weekday = str(today_user.weekday())
            day_lines = employee.resource_calendar_id.attendance_ids.filtered(
                lambda l: l.dayofweek == today_weekday
            )
            expected_seconds = sum(
                (l.hour_to - l.hour_from) * 3600 for l in day_lines
            )

        # Status label
        status_label_map = {
            'not_checked_in': 'Not Checked In',
            'checked_in': 'Working',
            'on_break': 'On Break',
            'checked_out': 'Completed',
        }
        status_label = status_label_map.get(current_status, 'Unknown')

        details_card = {
            "date": today_user.strftime("%d %b, %Y"),
            "day": today_user.strftime("%A"),
            "status_label": status_label,
            "check_in_time": clock_in_display,
            "check_out_time": clock_out_display,
            "break_start_time": break_start_display,
            "break_end_time": break_end_display,
            "worked_display": self._format_duration(total_worked_seconds),
            "break_display": self._format_duration(total_break_seconds),
            "expected_display": self._format_duration(expected_seconds),
            "work_sessions": work_sessions_count,
            "break_count": break_sessions_count,
        }

        return {
            "status": 200,
            "date": today_user.strftime("%d %b, %Y"),
            "current_status": current_status,
            "check_in_iso": check_in_iso,
            "break_start_iso": break_start_iso,
            "total_worked_seconds": int(total_worked_seconds),
            "total_break_seconds": int(total_break_seconds),
            "time_logs": {
                "clock_in": clock_in_display,
                "break_start": break_start_display,
                "break_end": break_end_display,
                "clock_out": clock_out_display
            },
            "office_location": office_info,
            "details_card": details_card,
        }


    @http.route('/mobile/payslip/dashboard', type='json', auth='user', csrf=False)
    def payslip_dashboard(self, **kwargs):
        user = request.env.user
        employee = request.env['hr.employee'].sudo().search(
            [('user_id', '=', user.id)], limit=1
        )
        if not employee:
            return {"status": 400, "error": "Employee not found for this user"}

        user_tz = pytz.timezone(user.tz or 'UTC')
        today_user = datetime.now(user_tz).date()

        upcoming_payslips = request.env['hr.payslip'].sudo().search([
            ('employee_id', '=', employee.id),
            ('date_to', '>=', today_user),
            ('state', 'in', ['draft', 'verify', 'done'])
        ], order='date_from ASC', limit=2)

        payslip_list = [{
            "name": payslip.name,
            "from_date": payslip.date_from.strftime('%d.%m.%Y'),
            "to_date": payslip.date_to.strftime('%d.%m.%Y'),
            "salary": payslip.amount if hasattr(payslip, 'amount')
            else payslip.line_ids.filtered(lambda l: l.code == 'NET').total,
        } for payslip in upcoming_payslips]

        today_timesheets = request.env['account.analytic.line'].sudo().search([
            ('user_id', '=', user.id),
            ('date', '=', today_user)
        ])
        today_hours = sum(today_timesheets.mapped('unit_amount'))

        start_week = today_user - timedelta(days=today_user.weekday())
        week_chart = []

        for i in range(7):
            day = start_week + timedelta(days=i)
            timesheets = request.env['account.analytic.line'].sudo().search([
                ('user_id', '=', user.id),
                ('date', '=', day)
            ])
            total = sum(timesheets.mapped('unit_amount'))
            week_chart.append({
                "day": day.strftime('%a'),
                "date": day.strftime('%Y-%m-%d'),
                "hours": round(total, 2)
            })

        return {
            "status": 200,
            "next_payslips": payslip_list,
            "working_hours": {
                "today_hours": round(today_hours, 2),
                "weekly_chart": week_chart
            }
        }

    @http.route('/mobile/payslip/list', type='json', auth='user', csrf=False)
    def get_payslip_list(self, **kwargs):
        user = request.env.user
        employee = request.env['hr.employee'].sudo().search(
            [('user_id', '=', user.id)], limit=1
        )
        if not employee:
            return {"success": False, "message": "No employee found"}

        params = request.httprequest.args

        page = int(params.get('page', 1))
        limit = int(params.get('limit', 10))
        offset = (page - 1) * limit
        search = params.get('search', '')
        sort = params.get('sort', 'date_from desc')
        year = params.get('year')

        domain = [('employee_id', '=', employee.id)]

        if search:
            domain += ['|', ('name', 'ilike', search), ('number', 'ilike', search)]

        if year:
            try:
                year = int(year)
                year_start = f'{year}-01-01'
                year_end = f'{year}-12-31'

                domain += [
                    ('date_from', '<=', year_end),
                    ('date_to', '>=', year_start)
                ]
            except ValueError:
                return {"success": False, "message": "Invalid year format"}

        Payslip = request.env['hr.payslip'].sudo()

        total = Payslip.search_count(domain)
        total_pages = (total + limit - 1) // limit if limit else 1

        payslips = Payslip.search(
            domain,
            order=sort,
            limit=limit,
            offset=offset
        )

        data = []
        for slip in payslips:
            net_amount = slip.line_ids.filtered(
                lambda l: l.code == 'NET'
            ).total if slip.line_ids else 0.0

            data.append({
                'id': slip.id,
                'name': slip.name,
                'date_from': slip.date_from.strftime('%d.%m.%Y'),
                'date_to': slip.date_to.strftime('%d.%m.%Y'),
                'net': net_amount,
            })

        return {
            "status": 200,
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": total_pages,
            "payslips": data
        }


    @http.route('/mobile/payslip/detail', type='json', auth='user', csrf=False)
    def payslip_detail(self, **kwargs):
        data = request.get_json_data()
        payslip_id = data.get('payslip_id')
        if not payslip_id:
            return {"status": 400, "error": "Payslip ID is required"}

        payslip = request.env['hr.payslip'].sudo().browse(int(payslip_id))
        if not payslip or not payslip.employee_id:
            return {"status": 404, "error": "Payslip not found"}

        user = request.env.user
        if not user.has_group('hr_payroll.group_hr_payroll_user') and payslip.employee_id.user_id.id != user.id:
            return {"status": 403, "error": "You do not have permission to access this payslip."}

        details = {}
        for line in payslip.line_ids:
            details[line.name] = line.total

        company_name = payslip.company_id.name or ''
        company_address = payslip.company_id.city or ''
        full_location = f"{company_address}, UAE" if company_address else "UAE"

        response = {
            "status": 200,
            "payslip_detail": {
                "name": payslip.name,
                "date_from": str(payslip.date_from),
                "date_to": str(payslip.date_to),
                "company": company_name,
                "location": full_location,
                "net_total": payslip.line_ids.filtered(lambda l: l.code == 'NET').total if payslip.line_ids else 0.0,
                "details": details,
                "grand_total": sum(details.values())
            }
        }
        return response

    @http.route('/mobile/document/list', type='json', auth='user', csrf=False)
    def get_document_list(self, **kwargs):
        data = request.get_json_data()
        user = request.env.user

        employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        if not employee:
            return {"status": 400, "error": "No employee found"}

        page = int(data.get('page', 1))
        limit = int(data.get('limit', 10))
        offset = (page - 1) * limit
        search = data.get('search', '')

        domain = [('employee_id', '=', employee.id)]
        if search:
            domain += [('document_id.name', 'ilike', search)]

        Document = request.env['hr.employee.document'].sudo()
        total = Document.search_count(domain)
        total_pages = (total + limit - 1) // limit if limit else 1

        documents = Document.search(domain, limit=limit, offset=offset, order="issue_date desc")

        result = []
        for doc in documents:
            result.append({
                "id": doc.id,
                "name": doc.document_id.name,
                "document_number": doc.name,
                "issue_date": doc.issue_date.strftime('%d/%m/%Y - %I:%M %p') if doc.issue_date else '',
                "expiry_date": doc.expiry_date.strftime('%d/%m/%Y') if doc.expiry_date else '',
                "description": doc.description or '',
                "has_attachment": bool(doc.doc_attachment_ids)
            })

        return {
            "status": 200,
            "total": total,
            "total_pages": total_pages,
            "page": page,
            "limit": limit,
            "documents": result
        }

    @http.route('/mobile/payslip/download_base64', type='json', auth='user', csrf=False)
    def download_payslip_pdf_base64(self, **kwargs):
        data = request.get_json_data()
        payslip_id = data.get('payslip_id')

        if not payslip_id:
            return {"status": 400, "error": "Missing payslip_id"}

        payslip = request.env['hr.payslip'].sudo().browse(int(payslip_id))
        if not payslip or not payslip.exists():
            return {"status": 404, "error": "Payslip not found"}

        report_name = 'hr_payroll.report_payslip_lang'
        pdf_content, _ = request.env['ir.actions.report'] \
            .sudo() \
            .with_context(lang=payslip.employee_id.lang or request.env.lang) \
            ._render_qweb_pdf(report_name, [payslip.id])

        pdf_base64 = base64.b64encode(pdf_content).decode('utf-8')
        filename = f"{payslip.name or 'Payslip'}.pdf"

        return {
            "status": 200,
            "filename": filename,
            "content_type": "application/pdf",
            "base64_pdf": pdf_base64,
        }

    @http.route('/mobile/events/upcoming', type='json', auth='user', csrf=False)
    def get_upcoming_events(self, **kwargs):
        page = int(kwargs.get('page', 1))
        limit = int(kwargs.get('limit', 10))
        offset = (page - 1) * limit
        search = kwargs.get('search', '')

        domain = [('date_begin', '>=', fields.Datetime.now())]
        if search:
            domain += ['|', ('name', 'ilike', search), ('address_id.name', 'ilike', search)]

        Event = request.env['event.event'].sudo()
        total = Event.search_count(domain)
        total_pages = math.ceil(total / limit) if limit else 1

        events = Event.search(domain, order='date_begin asc', limit=limit, offset=offset)

        result = []
        for event in events:
            result.append({
                "id": event.id,
                "name": event.name,
                "start_datetime": fields.Datetime.context_timestamp(
                        request.env.user.with_context(tz=request.env.user.tz),
                        event.date_begin
                    ).strftime('%Y-%m-%d %H:%M:%S') if event.date_begin else '',
                "end_datetime": fields.Datetime.context_timestamp(
                        request.env.user.with_context(tz=request.env.user.tz),
                        event.date_end
                    ).strftime('%Y-%m-%d %H:%M:%S') if event.date_end else '',
                "location": event.address_id.name if event.address_id else '',
                "seats_max": event.seats_max or 0,
                "seats_available": event.seats_available or 0,
                "description": event.description or '',
            })

        return {
            "status": 200,
            "total": total,
            "total_pages": total_pages,
            "page": page,
            "limit": limit,
            "events": result,
        }

    @http.route('/mobile/announcements/list', type='json', auth='user', csrf=False)
    def get_announcement_list(self, **kwargs):
        data = request.get_json_data()
        user = request.env.user.sudo()
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)

        if not employee:
            return {"status": 400, "error": "No employee found"}

        page = int(data.get('page', 1))
        limit = int(data.get('limit', 10))
        offset = (page - 1) * limit
        search = data.get('search', '')

        today = date.today()

        domain = [
            ('state', '=', 'approved'),
            # ('date_start', '<=', today),
            # ('date_end', '>=', today),
            '|',
            ('is_announcement', '=', True),
            '|',
            '|',
            ('employee_ids', 'in', employee.id),
            ('department_ids', 'in', employee.department_id.id if employee.department_id else False),
            ('position_ids', 'in', employee.job_id.id if employee.job_id else False),
        ]

        if search:
            domain += ['|', ('announcement_reason', 'ilike', search), ('announcement', 'ilike', search)]

        Announcement = request.env['hr.announcement'].sudo()
        announcements = Announcement.search(domain, offset=offset, limit=limit, order="date_start desc")
        print("..Announcement.", announcements)

        total = Announcement.search_count(domain)
        total_pages = (total + limit - 1) // limit

        result = []
        for ann in announcements:
            result.append({
                "id": ann.id,
                "title": ann.announcement_reason,
                "start_date": ann.date_start.strftime('%d-%m-%Y') if ann.date_start else '',
                "end_date": ann.date_end.strftime('%d-%m-%Y') if ann.date_end else '',
                "body": ann.announcement,
                "is_general": ann.is_announcement,
                "company": ann.company_id.name if ann.company_id else '',
            })

        return {
            "status": 200,
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": total_pages,
            "announcements": result
        }

    @http.route('/mobile/attendance/check', type='json', auth='user', csrf=False)
    def mobile_attendance_check(self, **kwargs):
        data = request.get_json_data() or {}
        action = data.get('action')
        lat = data.get('latitude')
        lon = data.get('longitude')

        if action not in ('check_in', 'check_out', 'break_start', 'break_end'):
            return {"success": False, "message": "Invalid action"}

        if lat is None or lon is None:
            return {
                "success": False,
                "message": "Location access is required to use attendance.",
                "error_code": "LOCATION_MISSING"
            }

        user = request.env.user
        employee = request.env['hr.employee'].sudo().search(
            [('user_id', '=', user.id)], limit=1
        )
        if not employee:
            return {"success": False, "message": "Employee not linked with user"}

        office_lat = employee.office_latitude
        office_lon = employee.office_longitude
        allowed_radius = employee.allowed_radius_m or 100

        if not office_lat or not office_lon:
            return {
                "success": False,
                "message": "Your office location has not been configured. Please contact HR.",
                "error_code": "OFFICE_LOCATION_NOT_SET"
            }

        distance = self._distance_in_meters(lat, lon, office_lat, office_lon)

        # ✅ Always return location context in every response (success or fail)
        location_context = {
            "user_location": {"latitude": lat, "longitude": lon},
            "office_location": {"latitude": office_lat, "longitude": office_lon},
            "distance_meters": int(distance),
            "allowed_radius_meters": allowed_radius,
            "is_within_range": distance <= allowed_radius
        }

        if distance > allowed_radius:
            over_by = int(distance - allowed_radius)
            return {
                "success": False,
                "message": f"You are {int(distance)}m from the office. Please move {over_by}m closer (allowed radius: {allowed_radius}m).",
                "error_code": "OUT_OF_RANGE",
                "location": location_context
            }

        today_start, today_end, today_user = self._get_user_day_range_utc()
        Attendance = request.env['hr.attendance'].sudo()
        now = fields.Datetime.now()

        open_work = Attendance.search([
            ('employee_id', '=', employee.id),
            ('check_out', '=', False),
            ('is_break', '=', False),
        ], order='check_in desc', limit=1)

        open_break = Attendance.search([
            ('employee_id', '=', employee.id),
            ('check_out', '=', False),
            ('is_break', '=', True),
        ], order='check_in desc', limit=1)

        user_ctx = user.with_context(tz=user.tz)

        if action == 'check_in':
            if open_work or open_break:
                return {
                    "success": False,
                    "message": "You are already checked in.",
                    "error_code": "ALREADY_CHECKED_IN",
                    "location": location_context
                }
            rec = Attendance.create({
                'employee_id': employee.id,
                'check_in': now,
                'in_latitude': lat,
                'in_longitude': lon,
                'is_break': False
            })
            check_in_iso = fields.Datetime.context_timestamp(
                user_ctx, rec.check_in
            ).isoformat()
            return {
                "success": True,
                "message": "Checked in successfully. Have a productive day!",
                "attendance_id": rec.id,
                "check_in_iso": check_in_iso,
                "current_status": "checked_in",
                "location": location_context
            }

        if action == 'check_out':
            if open_break:
                return {
                    "success": False,
                    "message": "Please end your break before checking out.",
                    "error_code": "ON_BREAK",
                    "location": location_context
                }
            if not open_work:
                return {
                    "success": False,
                    "message": "No active work session found. Please check in first.",
                    "error_code": "NOT_CHECKED_IN",
                    "location": location_context
                }
            open_work.write({
                'check_out': now,
                'out_latitude': lat,
                'out_longitude': lon
            })
            # Calculate total worked seconds for today
            attendances_today = Attendance.search([
                ('employee_id', '=', employee.id),
                ('check_in', '>=', today_start),
                ('check_in', '<=', today_end),
                ('is_break', '=', False),
            ])
            total_seconds = sum(
                (a.check_out - a.check_in).total_seconds()
                for a in attendances_today if a.check_out
            )
            hours = int(total_seconds // 3600)
            minutes = int((total_seconds % 3600) // 60)
            return {
                "success": True,
                "message": f"Checked out successfully. Total worked: {hours}h {minutes}m.",
                "attendance_id": open_work.id,
                "total_worked_seconds": int(total_seconds),
                "current_status": "checked_out",
                "location": location_context
            }

        if action == 'break_start':
            if not open_work:
                return {
                    "success": False,
                    "message": "You must be checked in to start a break.",
                    "error_code": "NOT_CHECKED_IN",
                    "location": location_context
                }
            if open_break:
                return {
                    "success": False,
                    "message": "You are already on a break.",
                    "error_code": "ALREADY_ON_BREAK",
                    "location": location_context
                }
            open_work.write({
                'check_out': now,
                'out_latitude': lat,
                'out_longitude': lon
            })
            break_rec = Attendance.create({
                'employee_id': employee.id,
                'check_in': now,
                'in_latitude': lat,
                'in_longitude': lon,
                'is_break': True
            })
            break_start_iso = fields.Datetime.context_timestamp(
                user_ctx, break_rec.check_in
            ).isoformat()
            return {
                "success": True,
                "message": "Break started. Enjoy your break!",
                "attendance_id": break_rec.id,
                "break_start_iso": break_start_iso,
                "current_status": "on_break",
                "location": location_context
            }

        if action == 'break_end':
            if not open_break:
                return {
                    "success": False,
                    "message": "No active break found.",
                    "error_code": "NOT_ON_BREAK",
                    "location": location_context
                }
            open_break.write({
                'check_out': now,
                'out_latitude': lat,
                'out_longitude': lon
            })
            break_duration = int((now - open_break.check_in).total_seconds())
            work_rec = Attendance.create({
                'employee_id': employee.id,
                'check_in': now,
                'in_latitude': lat,
                'in_longitude': lon,
                'is_break': False
            })
            check_in_iso = fields.Datetime.context_timestamp(
                user_ctx, work_rec.check_in
            ).isoformat()
            return {
                "success": True,
                "message": "Welcome back! Work session resumed.",
                "attendance_id": work_rec.id,
                "break_duration_seconds": break_duration,
                "check_in_iso": check_in_iso,
                "current_status": "checked_in",
                "location": location_context
            }
    def _distance_in_meters(self, lat1, lon1, lat2, lon2):
        R = 6371000
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)

        a = (
            math.sin(dphi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2)
            * math.sin(dlambda / 2) ** 2
        )
        return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


    @http.route('/mobile/logout', type='json', auth='user', methods=['POST'], csrf=False)
    def mobile_logout(self, **kwargs):
        """
        Logs out the currently authenticated mobile user.
        Works for normal and portal users since it's session-based.
        """
        try:
            if not request.session.uid:
                return {
                    "status": 400,
                    "error": "No active session"
                }

            request.session.logout()
            return {
                "status": 200,
                "message": "Logged out successfully"
            }
        except Exception as e:
            return {
                "status": 500,
                "error": str(e)
            }

    @http.route('/mobile/employee/document/download_base64', type='json', auth='user', csrf=False)
    def download_employee_document_base64(self, **kwargs):
        """
        Download an employee document attachment in Base64 format.
        Request JSON:
        {
            "document_id": 1,
            "attachment_id": 5   # optional
        }
        """
        data = request.get_json_data()
        document_id = data.get("document_id")
        attachment_id = data.get("attachment_id")

        if not document_id:
            return {"status": 400, "error": "Missing document_id"}

        user = request.env.user
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)

        document = request.env['hr.employee.document'].sudo().browse(int(document_id))
        print("..document.", document)
        if not document.exists():
            return {"status": 404, "error": "Document not found"}

        if not user.has_group('hr.group_hr_user'):
            if not employee or document.employee_id.id != employee.id:
                return {"status": 403, "error": "You don't have permission to access this document"}

        if attachment_id:
            attachment = document.doc_attachment_ids.filtered(lambda a: a.id == int(attachment_id))
            if not attachment:
                return {"status": 404, "error": "Attachment not found for this document"}
        else:
            attachment = document.doc_attachment_ids[:1]
            print("...")

        if not attachment or not attachment.datas:
            return {"status": 404, "error": "No attachment file found"}

        file_base64 = attachment.datas.decode('utf-8')

        return {
            "status": 200,
            "filename": attachment.name,
            "content_type": attachment.mimetype or "application/octet-stream",
            "base64_file": file_base64,
        }

    @http.route('/mobile/document/upload',type='http',auth='user',methods=['POST'],csrf=False)
    def upload_employee_document(self, **kwargs):

        user = request.env.user

        employee = request.env['hr.employee'].sudo().search(
            [('user_id', '=', user.id)],
            limit=1
        )

        if not employee:
            return request.make_json_response({
                "status": 400,
                "error": "No employee found"
            })

        document_id = kwargs.get('document_id')
        document_number = kwargs.get('document_number')
        issue_date = kwargs.get('issue_date')
        expiry_date = kwargs.get('expiry_date')
        description = kwargs.get('description')

        uploaded_file = request.httprequest.files.get('attachment')

        if not document_id:
            return request.make_json_response({
                "status": 400,
                "error": "document_id is required"
            })

        if not uploaded_file:
            return request.make_json_response({
                "status": 400,
                "error": "attachment is required"
            })

        allowed_types = [
            'image/jpeg',
            'image/png',
            'application/pdf'
        ]

        if uploaded_file.content_type not in allowed_types:
            return request.make_json_response({
                "status": 400,
                "error": "Only JPG, PNG and PDF files are allowed"
            })

        uploaded_file.seek(0, 2)
        file_size = uploaded_file.tell()
        uploaded_file.seek(0)

        max_size = 10 * 1024 * 1024

        if file_size > max_size:
            return request.make_json_response({
                "status": 400,
                "error": "File size exceeds 10 MB limit"
            })

        document = request.env['hr.employee.document'].sudo().create({
            'employee_id': employee.id,
            'document_id': int(document_id),
            'name': document_number,
            'issue_date': issue_date or False,
            'expiry_date': expiry_date or False,
            'description': description or '',
        })

        file_content = uploaded_file.read()

        attachment = request.env['ir.attachment'].sudo().create({
            'name': uploaded_file.filename,
            'datas': base64.b64encode(file_content),
            'res_model': 'hr.employee.document',
            'res_id': document.id,
            'mimetype': uploaded_file.content_type,
            'type': 'binary',
        })

        document.write({
            'doc_attachment_ids': [(4, attachment.id)]
        })

        return request.make_json_response({
            "status": 200,
            "message": "Document uploaded successfully",
            "document_id": document.id,
            "attachment_id": attachment.id,
            "file_name": attachment.name
        })
    
    @http.route('/mobile/tasks', type='json', auth='user', methods=['POST'], csrf=False)
    def mobile_task_list(self, **kwargs):

        user = request.env.user
        Task = request.env['project.task'].sudo()

        data = request.get_json_data() or {}

        page = int(data.get('page', 1))
        limit = int(data.get('limit', 10))
        offset = (page - 1) * limit

        domain = [
            ('user_ids', 'in', user.id)
        ]

        if data.get('status'):
            domain.append(('stage_id.name', '=', data.get('status')))

        total = Task.search_count(domain)

        tasks = Task.search(
            domain,
            order='id desc',
            limit=limit,
            offset=offset
        )

        result = []
        for task in tasks:
            result.append({
                "id": task.id,
                "name": task.name,
                "project": task.project_id.name if task.project_id else "",
                "stage_id": task.stage_id.id if task.stage_id else None,
                "status": task.stage_id.name if task.stage_id else "",
                "deadline": task.date_deadline or False,
                "priority": task.priority,
            })

        return {
            "status": 200,
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit if limit else 1,
            "count": len(result),
            "tasks": result
        }


    @http.route('/mobile/tasks/change_status', type='json', auth='user', csrf=False)
    def mobile_task_change_status(self, **kwargs):

        data = request.get_json_data() or {}
        task_id = data.get('task_id')
        stage_id = data.get('stage_id')

        if not task_id or not stage_id:
            return {
                "status": 400,
                "message": "task_id and stage_id are required"
            }

        user = request.env.user
        Task = request.env['project.task'].sudo()
        Stage = request.env['project.task.type'].sudo()

        task = Task.browse(int(task_id))
        if not task.exists():
            return {
                "status": 404,
                "message": "Task not found"
            }

        if user not in task.user_ids:
            return {
                "status": 403,
                "message": "You are not assigned to this task"
            }

        stage = Stage.browse(int(stage_id))
        if not stage.exists():
            return {
                "status": 404,
                "message": "Stage not found"
            }

        task.write({'stage_id': stage.id})

        return {
            "status": 200,
            "message": "Task status updated successfully",
            "task": {
                "id": task.id,
                "name": task.name,
                "stage_id": task.stage_id.id,
                "stage_name": task.stage_id.name
            }
        }
    

    @http.route('/mobile/calendar', type='json', auth='user', csrf=False)
    def mobile_calendar(self, **kwargs):

        data = request.get_json_data() or {}

        start_date = data.get('start_date')
        end_date = data.get('end_date')

        # NEW
        category = data.get('category')

        if not start_date or not end_date:
            return {
                "status": 400,
                "message": "start_date and end_date are required"
            }

        user = request.env.user

        employee = request.env['hr.employee'].sudo().search(
            [('user_id', '=', user.id)],
            limit=1
        )

        if not employee:
            return {
                "status": 400,
                "message": "Employee not linked with user"
            }

        user_tz = pytz.timezone(user.tz or 'UTC')

        start_user = user_tz.localize(
            datetime.combine(
                fields.Date.from_string(start_date),
                time.min
            )
        )

        end_user = user_tz.localize(
            datetime.combine(
                fields.Date.from_string(end_date),
                time.max
            )
        )

        start_utc = start_user.astimezone(pytz.utc)
        end_utc = end_user.astimezone(pytz.utc)

        calendar_data = []

        # =====================================================
        # TASKS
        # =====================================================

        if not category or category == 'task':

            tasks = request.env['project.task'].sudo().search([
                ('date_deadline', '>=', start_date),
                ('date_deadline', '<=', end_date),
                ('user_ids', 'in', user.id)
            ])

            for task in tasks:
                calendar_data.append({
                    "type": "task",
                    "id": task.id,
                    "title": task.name,
                    "start": task.date_deadline,
                    "end": task.date_deadline,
                    "color": "#4CAF50",
                    "status": task.stage_id.name if task.stage_id else ""
                })

        # =====================================================
        # LEAVES
        # =====================================================

        if not category or category == 'leave':

            leaves = request.env['hr.leave'].sudo().search([
                ('employee_id', '=', employee.id),
                ('request_date_from', '<=', end_date),
                ('request_date_to', '>=', start_date),
                ('state', 'in', ['confirm', 'validate'])
            ])

            for leave in leaves:
                calendar_data.append({
                    "type": "leave",
                    "id": leave.id,
                    "title": leave.holiday_status_id.name,
                    "start": leave.request_date_from,
                    "end": leave.request_date_to,
                    "color": "#FF9800",
                    "status": leave.state
                })

        # =====================================================
        # EVENTS
        # =====================================================

        if not category or category == 'event':

            events = request.env['event.event'].sudo().search([
                ('date_begin', '<=', end_utc),
                ('date_end', '>=', start_utc)
            ])

            for event in events:
                calendar_data.append({
                    "type": "event",
                    "id": event.id,
                    "title": event.name,
                    "start": fields.Datetime.context_timestamp(
                        user,
                        event.date_begin
                    ).strftime('%Y-%m-%d %H:%M:%S') if event.date_begin else '',

                    "end": fields.Datetime.context_timestamp(
                        user,
                        event.date_end
                    ).strftime('%Y-%m-%d %H:%M:%S') if event.date_end else '',

                    "color": "#2196F3",
                    "location": event.address_id.name if event.address_id else ""
                })

        return {
            "status": 200,
            "category": category or "all",
            "count": len(calendar_data),
            "calendar": calendar_data
        }

    @http.route('/mobile/profile', type='json', auth='user', csrf=False)
    def mobile_profile(self, **kwargs):
        user = request.env.user
        if not user:
            return {"status": 401, "message": "Session expired"}

        partner = user.partner_id
        employee = request.env['hr.employee'].sudo().search(
            [('user_id', '=', user.id)], limit=1
        )

        # ✅ URL only — never send base64 on profile screen
        # base64 causes heavy payload which pushes UI elements down
        # and hides content beneath navigation buttons
        profile_image_url = self.get_image_url('res.users', user.id, 'image_1920')

        return {
            "status": 200,
            "uid": user.id,
            "username": user.login,

            # Personal info
            "name": user.name or "",
            "street": partner.street or "",
            "city": partner.city or "",
            "zip": partner.zip or "",
            "country_code": partner.country_id.code if partner.country_id else "",
            "country": partner.country_id.name if partner.country_id else "",
            "state_code": partner.state_id.code if partner.state_id else "",
            "state": partner.state_id.name if partner.state_id else "",

            # Employee info
            "employee_id": employee.id if employee else None,
            "job_title": employee.job_title if employee else "",
            "department": employee.department_id.name if employee and employee.department_id else "",
            "work_email": employee.work_email if employee else "",
            "birthday": employee.birthday.strftime('%d.%m.%Y') if employee and employee.birthday else "",
            "phone": employee.private_phone if employee else "",
            "manager_name": employee.parent_id.name if employee and employee.parent_id else "",
            "manager_job_title": employee.parent_id.job_title if employee and employee.parent_id else "",

            # Timezone
            "timezone": user.tz or "UTC",

            # ✅ Image URL only — mobile uses this in Image component directly
            # Removing base64 fixes the Safe Area / content hidden issue
            "profile_image_url": profile_image_url,
        }

    @http.route('/mobile/profile/update', type='http', auth='user', methods=['POST'], csrf=False)
    def mobile_profile_update(self, **kwargs):

        user = request.env.user
        partner = user.partner_id

        name = kwargs.get('name')
        timezone = kwargs.get('timezone')
        number = kwargs.get('number')

        if name:
            partner.sudo().write({'name': name})

        if timezone:
            if timezone not in pytz.common_timezones:
                return request.make_json_response({
                    "status": 400,
                    "message": "Invalid timezone"
                })

            user.sudo().write({'tz': timezone})
            request.session['tz'] = timezone

        if number:
            partner.sudo().write({'phone': number})

        image_file = request.httprequest.files.get("image")

        if image_file:
            image_base64 = base64.b64encode(image_file.read())
            partner.sudo().write({
                "image_1920": image_base64
            })

        return request.make_json_response({
            "status": 200,
            "message": "Profile updated successfully",
            "timezone": user.tz
        })


    @http.route('/mobile/tasks/status', type='json', auth='user', methods=['POST'], csrf=False)
    def mobile_task_status_list(self, **kwargs):

        Stage = request.env['project.task.type'].sudo()

        stages = Stage.search([], order='sequence asc')

        result = []
        for stage in stages:
            result.append({
                "id": stage.id,
                "name": stage.name
            })

        return {
            "status": 200,
            "count": len(result),
            "statuses": result
        }

    @http.route('/mobile/chat/channel', type='json', auth='user', methods=['POST'], csrf=False)
    def get_or_create_chat_channel(self, **kwargs):
        """
        Get or create a direct chat channel between
        logged-in user and another user.
        """

        data = request.get_json_data() or {}
        target_user_id = data.get('user_id')

        if not target_user_id:
            return {
                "status": 400,
                "error": "user_id is required"
            }

        env = request.env
        current_user = env.user
        current_partner = current_user.partner_id

        target_user = env['res.users'].sudo().browse(int(target_user_id))
        if not target_user.exists():
            return {
                "status": 404,
                "error": "Target user not found"
            }

        target_partner = target_user.partner_id

        Channel = env['discuss.channel'].sudo()

        #SAFE search: direct chat with exactly these two partners
        channel = Channel.search([
            ('channel_type', '=', 'chat'),
            ('channel_partner_ids', 'in', [current_partner.id]),
            ('channel_partner_ids', 'in', [target_partner.id]),
        ], limit=1)

        #Create if missing
        if not channel:
            channel = Channel.create({
                'channel_type': 'chat',
                'channel_partner_ids': [
                    (4, current_partner.id),
                    (4, target_partner.id),
                ],
            })

        return {
            "status": 200,
            "channel_id": channel.id,
            "channel_name": channel.name,
            "participants": [
                current_partner.name,
                target_partner.name
            ]
        }
        
    @http.route('/mobile/chat/message/send', type='json', auth='user', methods=['POST'], csrf=False)
    def send_chat_message(self, **kwargs):
        data = request.get_json_data() or {}
        channel_id = data.get('channel_id')
        body = data.get('body')

        if not channel_id or not body:
            return {"status": 400, "error": "channel_id and body are required"}

        channel = request.env['discuss.channel'].sudo().browse(int(channel_id))
        if not channel.exists():
            return {"status": 404, "error": "Channel not found"}

        message = channel.message_post(
            body=body,
            message_type='comment',
            subtype_xmlid='mail.mt_comment'
        )

        return {
            "status": 200,
            "message_id": message.id,
            "channel_id": channel.id
        }


    @http.route('/mobile/chat/messages', type='json', auth='user', methods=['POST'], csrf=False)
    def get_chat_messages(self, **kwargs):

        data = request.get_json_data() or {}

        channel_id = data.get('channel_id')
        page = int(data.get('page', 1))
        limit = int(data.get('limit', 20))
        offset = (page - 1) * limit

        if not channel_id:
            return {"status": 400, "error": "channel_id is required"}

        channel = request.env['discuss.channel'].sudo().browse(int(channel_id))
        if not channel.exists():
            return {"status": 404, "error": "Channel not found"}

        user = request.env.user
        partner = user.partner_id
        user_ctx = user.with_context(tz=user.tz)

        #Update channel member (THIS fixes unread logic properly)
        member = request.env['discuss.channel.member'].sudo().search([
            ('channel_id', '=', channel.id),
            ('partner_id', '=', partner.id)
        ], limit=1)

        if member:
            member.sudo().write({
                'last_interest_dt': fields.Datetime.now()
            })

        #Mark notifications as read
        request.env['mail.notification'].sudo().search([
            ('res_partner_id', '=', partner.id),
            ('mail_message_id.model', '=', 'discuss.channel'),
            ('mail_message_id.res_id', '=', channel.id),
            ('is_read', '=', False)
        ]).write({'is_read': True})

        #Push bus update so UI refreshes unread counter
        if member:
            request.env['bus.bus']._sendone(
                partner,
                'mail.record/insert',
                {
                    'discuss.channel.member': [{
                        'id': member.id,
                        'message_unread_counter': 0,
                        'thread': {
                            'id': channel.id,
                            'model': 'discuss.channel'
                        }
                    }]
                }
            )

        #Fetch messages
        domain = [
            ('model', '=', 'discuss.channel'),
            ('res_id', '=', channel.id),
        ]

        Message = request.env['mail.message'].sudo()

        total = Message.search_count(domain)

        messages = Message.search(
            domain,
            order='id desc',
            limit=limit,
            offset=offset
        )

        result = []
        for msg in messages:
            result.append({
                "message_id": msg.id,
                "body": msg.body,
                "author": msg.author_id.name,
                "date": fields.Datetime.context_timestamp(
                    user_ctx,
                    msg.create_date
                ).strftime("%Y-%m-%d %H:%M:%S")
            })

        return {
            "status": 200,
            "page": page,
            "limit": limit,
            "total_records": total,
            "total_pages": (total + limit - 1) // limit,
            "messages": list(reversed(result))
        }


    @http.route('/mobile/chat/unread_count', type='json', auth='user', methods=['POST'], csrf=False)
    def unread_count(self, **kwargs):
        partner = request.env.user.partner_id

        members = request.env['discuss.channel.member'].sudo().search([
            ('partner_id', '=', partner.id)
        ])

        total = sum(m.message_unread_counter for m in members)

        return {
            "status": 200,
            "unread_count": total
        }

    @http.route('/mobile/chat/list', type='json', auth='user', methods=['POST'], csrf=False)
    def chat_list(self, **kwargs):

        data = request.get_json_data() or {}

        user = request.env.user
        user_ctx = user.with_context(tz=user.tz)

        partner = user.partner_id
        page = int(data.get('page', 1))
        limit = int(data.get('limit', 20))

        Member = request.env['discuss.channel.member'].sudo()

        members = Member.search([
            ('partner_id', '=', partner.id)
        ])

        chats = []

        for m in members:
            channel = m.channel_id

            # Last message
            last_msg = request.env['mail.message'].sudo().search([
                ('model', '=', 'discuss.channel'),
                ('res_id', '=', channel.id)
            ], order='create_date desc', limit=1)

            last_dt = None
            if last_msg and last_msg.create_date:
                last_dt = fields.Datetime.context_timestamp(
                    user_ctx,
                    last_msg.create_date
                )

            unread_count = request.env['mail.message'].sudo().search_count([
                ('model', '=', 'discuss.channel'),
                ('res_id', '=', channel.id),
                ('create_date', '>', m.last_interest_dt or datetime.min),
                ('author_id', '!=', partner.id)
            ])

            chats.append({
                "channel_id": channel.id,
                "channel_name": channel.name,
                "unread_count": unread_count,
                "last_message": last_msg.body if last_msg else "",
                "last_message_date": last_dt,
            })

        aware_min = datetime.min.replace(tzinfo=pytz.UTC)

        chats = sorted(
            chats,
            key=lambda x: x['last_message_date'] or aware_min,
            reverse=True
        )

        for chat in chats:
            if chat["last_message_date"]:
                chat["last_message_date"] = chat["last_message_date"].strftime("%Y-%m-%d %H:%M:%S")

        total = len(chats)
        start = (page - 1) * limit
        end = start + limit

        return {
            "status": 200,
            "page": page,
            "limit": limit,
            "total_records": total,
            "total_pages": (total + limit - 1) // limit,
            "chats": chats[start:end]
        }



    @http.route('/mobile/chat/mark_read', type='json', auth='user', methods=['POST'], csrf=False)
    def mark_chat_read(self, **kwargs):
        data = request.get_json_data() or {}
        channel_id = data.get("channel_id")

        if not channel_id:
            return {"status": 400, "error": "channel_id required"}

        partner = request.env.user.partner_id

        member = request.env['discuss.channel.member'].sudo().search([
            ('channel_id', '=', int(channel_id)),
            ('partner_id', '=', partner.id)
        ], limit=1)

        if not member:
            return {"status": 404, "error": "Channel membership not found"}

        member.sudo().write({
            'last_interest_dt': fields.Datetime.now()
        })

        request.env['bus.bus']._sendone(
            partner,
            'mail.record/insert',
            {
                'discuss.channel.member': [{
                    'id': member.id,
                    'message_unread_counter': 0,
                    'thread': {
                        'id': int(channel_id),
                        'model': 'discuss.channel'
                    }
                }]
            }
        )

        return {
            "status": 200,
            "message": "Messages marked as read"
        }



    @http.route('/mobile/employees', type='json', auth='user', methods=['POST'], csrf=False)
    def mobile_employees(self, **kwargs):

        data = request.get_json_data() or {}

        page = int(data.get("page", 1))
        limit = int(data.get("limit", 20))
        search = data.get("search", "")
        offset = (page - 1) * limit

        user = request.env.user

        domain = [
            ("active", "=", True),
            ("user_id", "!=", user.id)
        ]

        if search:
            domain += ["|",
                ("name", "ilike", search),
                ("work_email", "ilike", search)
            ]

        Employee = request.env["hr.employee"].sudo()

        total = Employee.search_count(domain)

        employees = Employee.search(
            domain,
            limit=limit,
            offset=offset,
            order="name asc"
        )

        result = []
        for emp in employees:
            result.append({
                "employee_id": emp.id,
                "name": emp.name,
                "job_title": emp.job_title or "",
                "email": emp.work_email or "",
            })

        return {
            "status": 200,
            "page": page,
            "limit": limit,
            "total_records": total,
            "total_pages": (total + limit - 1) // limit,
            "employees": result
        }


