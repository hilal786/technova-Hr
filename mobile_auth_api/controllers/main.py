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

_logger = logging.getLogger(__name__)


class MobileApiHome(http.Controller):

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
        values = {}

        data = request.get_json_data()
        login_url = data.get("web_url")
        login = data.get("login")
        password = data.get("password")

        if not login_url or not login or not password:
            return {"status": 400, "error": "Missing login, password, or web_url"}

        request_host = request.httprequest.host_url.rstrip('/')
        print('...request_host.', request_host)

        if login_url and not request_host.startswith(login_url):
            return {
                "status": 403,
                "error": f"Login blocked: Host mismatch. Expected base {login_url}, got {request_host}"
            }

        if request.httprequest.method == 'POST' and request.session.uid:
            user = request.env['res.users'].browse(request.session.uid)
            return {
                "status": 200,
                'uid': request.session.uid,
                'db': request.session.db,
                'username': request.session.login,
                'auth_info': "Already Logged in",

                'name': user.name,
                'street': user.partner_id.street,
                'city': user.partner_id.city,
                'mobile': user.partner_id.mobile,
                'zip': user.partner_id.zip,
                'country_id': user.partner_id.country_id.with_user(request.session.uid).code,
                'state_id': user.partner_id.state_id.with_user(request.session.uid).code,
                'profile_image_url': self.get_image_url('res.users', user.id, 'image_1920'),
            }

        try:
            values['databases'] = http.db_list()
        except odoo.exceptions.AccessDenied:
            values['databases'] = None

        if request.httprequest.method == 'POST':
            try:
                credential = {key: value for key, value in data.items() if
                              key in ['login', 'password', 'type'] and value}
                credential.setdefault('type', 'password')
                auth_info = request.session.authenticate(request.db, credential)
                request.params['login_success'] = True
                return {
                    "status": 200,
                    'uid': request.session.uid,
                    'db': request.session.db,
                    'username': request.session.login,
                    'auth_info': auth_info,

                    'name': request.env.user.name,
                    'street': request.env.user.partner_id.street,
                    'city': request.env.user.partner_id.city,
                    'mobile': request.env.user.partner_id.mobile,
                    'zip': request.env.user.partner_id.zip,
                    'country_id': request.env.user.partner_id.country_id.code,
                    'state_id': request.env.user.partner_id.state_id.code,
                    'profile_image_url': self.get_image_url('res.users', request.env.user.id, 'image_1920'),
                    'image_1920': request.env.user.image_1920,
                }
            except odoo.exceptions.AccessDenied as e:
                if e.args == odoo.exceptions.AccessDenied().args:
                    return {
                        "status": 401,
                        'error': "Wrong login/password",
                    }
                else:
                    return {
                        "status": 400,
                        'error': e.args[0],
                    }
        else:
            return {
                "status": 400,
                'error': 'Invalid request',
            }

    # @http.route('/mobile/expense/create', type='json', auth='none', csrf=False)
    # def create_expense(self, **kw):
    #     print("dsdsd",**kw)
    #     user = request.env.user
    #     print("....user", user)
    #     employee = user.employee_id
    #     print("..employee..", employee)
    #
    #     if not employee:
    #         return {"status": 400, "error": "User is not linked to any employee record"}
    #
    # data = request.get_json_data()
    # description = data.get('reason')
    # date = data.get('date')
    # amount = data.get('amount') or 10
    #
    #     if not all([description, date]):
    #         return {"status": 400, "error": "Missing required fields"}
    #     # 🔍 Get default expense product (first found with can_be_expensed = True)
    #     product = request.env['product.product'].sudo().search([('can_be_expensed', '=', True)], limit=1)
    #     if not product:
    #         return {"status": 400, "error": "No default expense product configured (can_be_expensed=True)"}
    #
    #     expense = request.env['hr.expense'].sudo().create({
    #         'name': description,
    #         'employee_id': employee.id,
    #         'date': date,
    #         'unit_amount': amount,
    #         'product_id': product.id,
    #
    #     })
    #     print("....expense.", expense)
    #
    #     return {"status": 200, "message": "Expense created", "expense_id": expense.id}
    #

    def _get_default_expense_product(self):
        product = request.env['product.product'].sudo().search(
            [('can_be_expensed', '=', True)],
            limit=1
        )
        return product

    @http.route('/mobile/expenses', type='json', auth='user', methods=['POST'], csrf=False)
    def create_expense(self, **post):
        print("....inside....")
        user = request.env.user
        print("....yser", user)
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        print("...employee", employee)
        if not employee:
            return {"status": 400, "error": "No employee linked to this user"}

        data = request.get_json_data()
        print("...data", data)
        description = data.get('reason')
        date = data.get('date')
        amount = data.get('amount') or 10

        # description = post.get("description")
        # amount = post.get("amount") or 10
        product_id = post.get("product_id") or self._get_default_expense_product().id

        if not description or not date:
            return {"status": 400, "error": "Missing required fields: description or date"}

        expense = request.env['hr.expense'].sudo().create({
            'name': description,
            'employee_id': employee.id,
            'product_id': product_id,
            'total_amount': float(amount),
            'date': date,
            'quantity': 1.0,
            'payment_mode': 'own_account',
        })

        return {"status": 200, "message": "Expense created", "expense_id": expense.id}

    @http.route('/mobile/expenses/list', type='json', auth='user', methods=['GET'], csrf=False)
    def list_expenses(self, **kwargs):
        user = request.env.user
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        if not employee:
            return {"status": 400, "error": "No employee linked to this user"}

        # Pagination parameters
        page = int(kwargs.get('page', 1))
        limit = int(kwargs.get('limit', 10))
        offset = (page - 1) * limit

        # Search domain
        domain = [('employee_id', '=', employee.id)]

        # Total count and page count
        total = request.env['hr.expense'].sudo().search_count(domain)
        total_pages = (total + limit - 1) // limit if limit else 1

        # Paged records
        expenses = request.env['hr.expense'].sudo().search(domain, offset=offset, limit=limit, order="date desc")

        result = []
        for exp in expenses:
            result.append({
                'id': exp.id,
                'name': exp.name,
                'amount': exp.total_amount,
                'state': exp.state,
                'date': str(exp.date),
            })

        return {
            "status": 200,
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": total_pages,
            "expenses": result
        }

    @http.route('/mobile/leaves/list', type='json', auth='user', methods=['GET'], csrf=False)
    def list_leaves(self, **kwargs):
        data = request.get_json_data()
        user = request.env.user
        domain = []

        # If not admin, restrict to logged-in employee
        if not user.has_group('base.group_system'):
            employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
            if not employee:
                return {"status": 400, "error": "No employee linked to this user"}
            domain.append(('employee_id', '=', employee.id))
        else:
            # Admin can filter by employee_id
            employee_id = data.get('employee_id')
            if employee_id:
                domain.append(('employee_id', '=', int(employee_id)))

        # Pagination & search
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

    @http.route('/mobile/leaves/types', type='json', auth='user', methods=['GET'], csrf=False)
    def get_available_leave_types(self, **kwargs):
        user = request.env.user

        # Find employee linked to logged-in user
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        if not employee:
            return {"status": 400, "error": "No employee linked to this user"}

        # Leave types allocated to this employee (validated allocations only)
        allocated_types = request.env['hr.leave.allocation'].sudo().search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'validate')
        ]).mapped('holiday_status_id.id')
        print('..allocated_types.', allocated_types)

        # Leave types that do NOT require allocation
        open_types = request.env['hr.leave.type'].sudo().search([
            ('requires_allocation', '=', False)
        ]).mapped('id')
        print("..open_types..", open_types)

        # Union both sets
        all_type_ids = list(set(allocated_types + open_types))
        print(".all_type_ids..", all_type_ids)

        leave_types = request.env['hr.leave.type'].sudo().browse(all_type_ids).read(['id', 'name'])

        return {
            "status": 200,
            "leave_types": leave_types
        }

    @http.route('/mobile/leaves/create', type='json', auth='user', methods=['POST'], csrf=False)
    def create_leave(self, **kwargs):
        print("..**kwargs..", **kwargs)
        user = request.env.user
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        if not employee:
            return {"status": 400, "error": "No employee linked to this user"}
        data = request.get_json_data()

        leave_type_id = data.get('leave_type_id')
        date_from = data.get('date_from')
        date_to = data.get('date_to')
        reason = data.get('reason')

        if not all([leave_type_id, date_from, date_to, reason]):
            print(".leave_type_id...", leave_type_id)
            print(".date_from...", date_from)
            print(".date_to...", date_to)
            print(".reason...", reason)
            return {"status": 400, "error": "Missing required fields"}

        try:
            leave = request.env['hr.leave'].sudo().create({
                'name': reason,
                'employee_id': employee.id,
                'holiday_status_id': int(leave_type_id),
                'request_date_from': date_from,
                'request_date_to': date_to,
            })
            return {
                "status": 200,
                "message": "Leave request submitted",
                "leave_id": leave.id
            }
        except Exception as e:
            return {"status": 500, "error": str(e)}

    # @http.route('/mobile/employee/profile', type='json', auth='user', csrf=False)
    # def employee_profile(self, **kwargs):
    #     user = request.env.user
    #     employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
    #     if not employee:
    #         return {"status": 400, "error": "No employee linked to this user"}
    #
    #     # This Week's Range
    #     today = fields.Date.today()
    #     start_week = today - timedelta(days=today.weekday())
    #     end_week = start_week + timedelta(days=6)
    #
    #     # Attendance Summary
    #     domain = [('employee_id', '=', employee.id), ('check_in', '>=', start_week), ('check_out', '<=', end_week)]
    #     attendances = request.env['hr.attendance'].sudo().search(domain)
    #     attendance_summary = {
    #         "present": 0,
    #         "absent": 0,
    #         "week_off": 0,
    #         "half_day": 0,
    #         "leave": 0,
    #         "holiday": 0,
    #     }
    #
    #     calendar = employee.resource_calendar_id
    #     if not calendar:
    #         calendar = employee.company_id.resource_calendar_id
    #
    #     holidays = request.env['resource.calendar.leaves'].sudo().search([
    #         ('calendar_id', '=', calendar.id),
    #         ('date_from', '<=', end_week),
    #         ('date_to', '>=', start_week)
    #     ])
    #
    #     leaves = request.env['hr.leave'].sudo().search([
    #         ('employee_id', '=', employee.id),
    #         ('request_date_from', '<=', end_week),
    #         ('request_date_to', '>=', start_week),
    #         ('state', 'in', ['validate'])
    #     ])
    #
    #     week_days = [start_week + timedelta(days=i) for i in range(7)]
    #     for day in week_days:
    #         day_att = [a for a in attendances if a.check_in.date() == day]
    #         if day_att:
    #             worked_hours = sum([(a.check_out - a.check_in).total_seconds() / 3600 for a in day_att if a.check_out])
    #             if worked_hours < 4:
    #                 attendance_summary["half_day"] += 1
    #             else:
    #                 attendance_summary["present"] += 1
    #         elif any(h.date_from.date() <= day <= h.date_to.date() for h in holidays):
    #             attendance_summary["holiday"] += 1
    #         elif any(l.request_date_from <= day <= l.request_date_to for l in leaves):
    #             attendance_summary["leave"] += 1
    #         elif not calendar.attendance_ids.filtered(lambda a: a.dayofweek == str(day.weekday())):
    #             attendance_summary["week_off"] += 1
    #         else:
    #             attendance_summary["absent"] += 1
    #
    #     timesheets = request.env['account.analytic.line'].sudo().search_read([
    #         ('employee_id', '=', employee.id),
    #         ('date', '=', fields.Date.today())
    #     ], ['unit_amount'])
    #
    #     timesheet_hours = sum(t['unit_amount'] for t in timesheets)
    #
    #     return {
    #         "status": 200,
    #         "employee": {
    #             "name": employee.name,
    #             "job_title": employee.job_title,
    #         },
    #         "timesheet_summary": {
    #             "today_hours": round(timesheet_hours, 2),
    #             "weekly_bar_chart": [],  # optionally add data per weekday
    #         },
    #         "attendance_summary": attendance_summary
    #     }
    #
    # @http.route('/mobile/employee/weekly_chart', type='json', auth='user', csrf=False)
    # def weekly_bar_chart(self, **kwargs):
    #     user = request.env.user
    #     employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
    #     if not employee:
    #         return {"status": 400, "error": "No employee linked to this user"}
    #
    #     today = fields.Date.today()
    #     chart_data = []
    #
    #     for i in range(7):
    #         day = today - timedelta(days=i)
    #         timesheets = request.env['account.analytic.line'].sudo().search_read([
    #             ('employee_id', '=', employee.id),
    #             ('date', '=', day)
    #         ], ['unit_amount'])
    #
    #         total_hours = sum(t['unit_amount'] for t in timesheets)
    #         chart_data.append({
    #             "date": str(day),
    #             "hours": total_hours
    #         })
    #
    #     # Sort by ascending date (oldest first)
    #     chart_data = sorted(chart_data, key=lambda x: x['date'])
    #
    #     return {
    #         "status": 200,
    #         "weekly_hours": chart_data
    #     }

    @http.route('/mobile/employee/profile', type='json', auth='user', csrf=False)
    def employee_profile(self, **kwargs):
        user = request.env.user
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        if not employee:
            return {"status": 400, "error": "No employee linked to this user"}

        today = fields.Date.today()
        start_week = today - timedelta(days=today.weekday())  # Monday
        end_week = start_week + timedelta(days=6)  # Sunday

        # Attendance Summary
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

        # Today's timesheet
        timesheets = request.env['account.analytic.line'].sudo().search_read([
            ('employee_id', '=', employee.id),
            ('date', '=', today)
        ], ['unit_amount'])

        timesheet_hours = sum(t['unit_amount'] for t in timesheets)

        # Weekly bar chart (timesheet hours for past 7 days)
        chart_data = []
        for i in range(7):
            day = today - timedelta(days=i)
            daily_timesheets = request.env['account.analytic.line'].sudo().search_read([
                ('employee_id', '=', employee.id),
                ('date', '=', day)
            ], ['unit_amount'])

            total_hours = sum(t['unit_amount'] for t in daily_timesheets)
            chart_data.append({
                "date": str(day),
                "hours": round(total_hours, 2)
            })

        # Sort the chart data by date ascending
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
            "attendance_summary": attendance_summary
        }

    @http.route('/mobile/attendance/logs', type='json', auth='user', csrf=False)
    def get_attendance_logs(self, **kwargs):
        user = request.env.user
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        if not employee:
            return {"status": 400, "error": "No employee linked to this user"}

        today = fields.Date.today()
        attendances = request.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', datetime.combine(today, datetime.min.time())),
            ('check_in', '<=', datetime.combine(today, datetime.max.time())),
        ], order='check_in asc')

        data = {
            "clock_in": None,
            "clock_out": None,
            "break_start": None,
            "break_end": None,
        }

        if attendances:
            # Assuming first check_in is clock-in and last check_out is clock-out
            data["clock_in"] = attendances[0].check_in.strftime("%H:%M:%S %p") if attendances[0].check_in else None
            data["clock_out"] = attendances[-1].check_out.strftime("%H:%M:%S %p") if attendances[-1].check_out else None

        # OPTIONAL: handle smoke break timings if managed using separate model or tags
        break_entries = request.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', datetime.combine(today, datetime.min.time())),
            ('check_in', '<=', datetime.combine(today, datetime.max.time())),
            # ('work_type', '=', 'break')  # Replace with your custom logic if any
        ])

        if break_entries:
            data["break_start"] = break_entries[0].check_in.strftime("%H:%M:%S %p") if break_entries[
                0].check_in else None
            data["break_end"] = break_entries[-1].check_out.strftime("%H:%M:%S %p") if break_entries[
                -1].check_out else None

        return {
            "status": 200,
            "date": today.strftime("%d %b, %Y"),
            "location": "Dubai silicon oasis, Dubai, UAE",  # Replace with dynamic GPS if applicable
            "time_logs": data
        }

    @http.route('/mobile/payslip/dashboard', type='json', auth='user', csrf=False)
    def payslip_dashboard(self, **kwargs):
        user = request.env.user
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        if not employee:
            return {"status": 400, "error": "Employee not found for this user"}

        # Today date
        today = fields.Date.today()

        # --- 1. Upcoming Payslips (limit 2) ---
        upcoming_payslips = request.env['hr.payslip'].sudo().search([
            ('employee_id', '=', employee.id),
            ('date_to', '>=', today),
            ('state', 'in', ['draft', 'verify', 'done'])  # optional: based on status needed
        ], order='date_from ASC', limit=2)

        payslip_list = [{
            "name": payslip.name,
            "from_date": payslip.date_from.strftime('%d.%m.%Y'),
            "to_date": payslip.date_to.strftime('%d.%m.%Y'),
            "salary": payslip.amount if hasattr(payslip, 'amount') else payslip.line_ids.filtered(
                lambda l: l.code == 'NET').total,
        } for payslip in upcoming_payslips]

        # --- 2. Working Hours Today ---
        today_timesheets = request.env['account.analytic.line'].sudo().search([
            ('employee_id', '=', employee.id),
            ('date', '=', today)
        ])
        today_hours = sum(today_timesheets.mapped('unit_amount'))

        # --- 3. Weekly Bar Chart (Mon-Sun) ---
        start_week = today - timedelta(days=today.weekday())
        week_chart = []
        for i in range(7):
            day = start_week + timedelta(days=i)
            timesheets = request.env['account.analytic.line'].sudo().search([
                ('employee_id', '=', employee.id),
                ('date', '=', day)
            ])
            total = sum(timesheets.mapped('unit_amount'))
            week_chart.append({
                "day": day.strftime('%a'),  # Mon, Tue, ...
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
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        if not employee:
            return {"status": 400, "error": "No employee found"}

        page = int(kwargs.get('page', 1))
        limit = int(kwargs.get('limit', 10))
        offset = (page - 1) * limit
        search = kwargs.get('search', '')
        sort = kwargs.get('sort', 'date_from desc')

        domain = [('employee_id', '=', employee.id)]
        if search:
            domain += ['|', ('name', 'ilike', search), ('number', 'ilike', search)]

        Payslip = request.env['hr.payslip'].sudo()
        total = Payslip.search_count(domain)
        total_pages = (total + limit - 1) // limit if limit else 1

        payslips = Payslip.search(domain, order=sort, limit=limit, offset=offset)

        data = []
        for slip in payslips:
            net_amount = slip.line_ids.filtered(lambda l: l.code == 'NET').total if slip.line_ids else 0.0
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

        # Access control: check if the user is allowed to see this payslip
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

        # Get employee linked to current user
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        if not employee:
            return {"status": 400, "error": "No employee found"}

        # Pagination & filters
        page = int(data.get('page', 1))
        limit = int(data.get('limit', 10))
        offset = (page - 1) * limit
        search = data.get('search', '')

        # Domain for current employee
        domain = [('employee_id', '=', employee.id)]
        if search:
            domain += [('document_id.name', 'ilike', search)]

        Document = request.env['hr.employee.document'].sudo()
        total = Document.search_count(domain)
        total_pages = (total + limit - 1) // limit if limit else 1

        documents = Document.search(domain, limit=limit, offset=offset, order="issue_date desc")

        # Prepare response
        result = []
        for doc in documents:
            result.append({
                "id": doc.id,
                "name": doc.document_id.name,  # Document type
                "document_number": doc.name,  # Document number
                "issue_date": doc.issue_date.strftime('%d/%m/%Y - %I:%M %p') if doc.issue_date else '',
                "expiry_date": doc.expiry_date.strftime('%d/%m/%Y') if doc.expiry_date else '',
                "description": doc.description or '',
            })

        return {
            "status": 200,
            "total": total,
            "total_pages": total_pages,
            "page": page,
            "limit": limit,
            "documents": result
        }

        # @http.route('/mobile/payslip/download', type='http', auth='user', csrf=False)
        # def download_payslip_pdf(self, payslip_id=None, **kwargs):
        #     data = request.get_json_data()
        #     payslip_id = data.get('payslip_id')
        #     if not payslip_id:
        #         return request.not_found()
        #
        #     payslip = request.env['hr.payslip'].sudo().browse(int(payslip_id))
        #     print(".payslip..",payslip)
        #     if not payslip or not payslip.exists():
        #         return request.not_found()
        #
        #     # Render PDF from QWeb report
        #     pdf_content, _ = request.env['ir.actions.report'] \
        #         .sudo() \
        #         .with_context(lang=payslip.employee_id.lang or request.env.lang) \
        #         ._render_qweb_pdf('hr_payroll.report_payslip_lang', [payslip.id])
        #
        #     # Build the file response
        #     pdf_file_name = f"{payslip.name or 'payslip'}.pdf"
        #     headers = [
        #         ('Content-Type', 'application/pdf'),
        #         ('Content-Disposition', f'attachment; filename="{pdf_file_name}"')
        #     ]
        #
        #     return request.make_response(pdf_content, headers=headers)

    @http.route('/mobile/payslip/download_base64', type='json', auth='user', csrf=False)
    def download_payslip_pdf_base64(self, **kwargs):
        data = request.get_json_data()
        payslip_id = data.get('payslip_id')

        # payslip_id = kwargs.get('payslip_id')
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
                "start_datetime": event.date_begin.strftime('%Y-%m-%d %H:%M:%S') if event.date_begin else '',
                "end_datetime": event.date_end.strftime('%Y-%m-%d %H:%M:%S') if event.date_end else '',
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

        # Build domain for announcements
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
        data = request.get_json_data()
        action = data.get('action')  # check_in or check_out

        user = request.env.user
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        if not employee:
            return {"status": 400, "error": "Employee not found for user."}

        attendance = request.env['hr.attendance'].sudo()
        last_attendance = attendance.search([('employee_id', '=', employee.id)], order="check_in desc", limit=1)

        if action == 'check_in':
            if last_attendance and not last_attendance.check_out:
                return {"status": 400, "error": "Already checked in. Please check out first."}
            checkin = attendance.create({
                'employee_id': employee.id,
                'check_in': fields.Datetime.now()
            })
            return {"status": 200, "message": "Checked in successfully", "attendance_id": checkin.id}

        elif action == 'check_out':
            if not last_attendance or last_attendance.check_out:
                return {"status": 400, "error": "No open check-in found to check out from."}
            last_attendance.write({
                'check_out': fields.Datetime.now()
            })
            return {"status": 200, "message": "Checked out successfully", "attendance_id": last_attendance.id}

        else:
            return {"status": 400, "error": "Invalid action. Use 'check_in' or 'check_out'."}
