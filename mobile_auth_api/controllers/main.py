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
from odoo.exceptions import ValidationError, UserError


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

    @http.route('/mobile/expenses', type='json', auth='user', methods=['POST'], csrf=False)
    def create_expense(self, **post):
        user = request.env.user
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        if not employee:
            return {"status": 400, "error": "No employee linked to this user"}

        data = request.get_json_data()
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
            [('user_id', '=', user.id)], limit=1
        )
        if not employee:
            return {"status": 400, "error": "No employee linked to this user"}

        data = request.get_json_data() or {}
        leave_type_id = data.get('leave_type_id')
        date_from = data.get('date_from')
        date_to = data.get('date_to')
        reason = data.get('reason')

        if not all([leave_type_id, date_from, date_to, reason]):
            return {"status": 400, "error": "Missing required fields"}

        existing_leave = request.env['hr.leave'].sudo().search([
            ('employee_id', '=', employee.id),
            ('state', '!=', 'cancel'),
            ('request_date_from', '<=', date_to),
            ('request_date_to', '>=', date_from),
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

        except (ValidationError, UserError) as e:
            return {
                "status": 400,
                "error": e.args[0]
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

    @http.route('/mobile/attendance/logs', type='json', auth='user', csrf=False)
    def mobile_attendance_log(self, **kwargs):
        user = request.env.user
        employee = request.env['hr.employee'].sudo().search(
            [('user_id', '=', user.id)], limit=1
        )
        if not employee:
            return {"status": 400, "error": "Employee not found for user."}

        today_start = fields.Datetime.to_datetime(fields.Date.today())
        today_end = today_start.replace(hour=23, minute=59, second=59)

        Attendance = request.env['hr.attendance'].sudo()

        attendances = Attendance.search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', today_start),
            ('check_in', '<=', today_end)
        ], order='check_in asc')

        clock_in = None
        clock_out = None
        break_start = None
        break_end = None

        if attendances:
            first_work_att = next(
                (att for att in attendances if not att.is_break and att.check_in),
                None
            )
            if first_work_att:
                clock_in = first_work_att.check_in.strftime("%I:%M:%S %p")

            break_checkins = [
                att.check_in for att in attendances
                if att.is_break and att.check_in
            ]
            if break_checkins:
                break_start = max(break_checkins).strftime("%I:%M:%S %p")

            break_checkouts = [
                att.check_out for att in attendances
                if att.is_break and att.check_out
            ]
            if break_checkouts:
                break_end = max(break_checkouts).strftime("%I:%M:%S %p")

            open_work = Attendance.search([
                ('employee_id', '=', employee.id),
                ('check_out', '=', False),
                ('is_break', '=', False)
            ], limit=1)

            work_checkouts = [
                att.check_out for att in attendances
                if not att.is_break and att.check_out
            ]

            if work_checkouts and not open_work:
                clock_out = max(work_checkouts).strftime("%I:%M:%S %p")

        return {
            "status": 200,
            "date": fields.Date.today().strftime("%d %b, %Y"),
            "time_logs": {
                "clock_in": clock_in,
                "break_start": break_start,
                "break_end": break_end,
                "clock_out": clock_out
            }
        }


    @http.route('/mobile/payslip/dashboard', type='json', auth='user', csrf=False)
    def payslip_dashboard(self, **kwargs):
        user = request.env.user
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        if not employee:
            return {"status": 400, "error": "Employee not found for this user"}

        today = fields.Date.today()

        upcoming_payslips = request.env['hr.payslip'].sudo().search([
            ('employee_id', '=', employee.id),
            ('date_to', '>=', today),
            ('state', 'in', ['draft', 'verify', 'done'])
        ], order='date_from ASC', limit=2)

        payslip_list = [{
            "name": payslip.name,
            "from_date": payslip.date_from.strftime('%d.%m.%Y'),
            "to_date": payslip.date_to.strftime('%d.%m.%Y'),
            "salary": payslip.amount if hasattr(payslip, 'amount') else payslip.line_ids.filtered(
                lambda l: l.code == 'NET').total,
        } for payslip in upcoming_payslips]

        today_timesheets = request.env['account.analytic.line'].sudo().search([
            ('user_id', '=', user.id),
            ('date', '=', today)
        ])
        today_hours = sum(today_timesheets.mapped('unit_amount'))

        start_week = today - timedelta(days=today.weekday())
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

        if action not in ('check_in', 'check_out', 'break_in', 'break_out'):
            return {
                "success": False,
                "message": "Invalid action"
            }

        if lat is None or lon is None:
            return {
                "success": False,
                "message": "Latitude and longitude are required"
            }

        user = request.env.user
        employee = request.env['hr.employee'].sudo().search(
            [('user_id', '=', user.id)], limit=1
        )

        if not employee:
            return {
                "success": False,
                "message": "Employee not linked with user"
            }

        office_lat = employee.office_latitude
        office_lon = employee.office_longitude
        allowed_radius = employee.allowed_radius_m or 100

        if not office_lat or not office_lon:
            return {
                "success": False,
                "message": "Office location not configured"
            }

        distance = self._distance_in_meters(lat, lon, office_lat, office_lon)
        if distance > allowed_radius:
            return {
                "success": False,
                "message": f"You are {int(distance)} meters away. Allowed radius is {allowed_radius} meters."
            }

        Attendance = request.env['hr.attendance'].sudo()

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

        now = fields.Datetime.now()

        if action == 'check_in':
            if open_work or open_break:
                return {
                    "success": False,
                    "message": "Already checked in"
                }

            rec = Attendance.create({
                'employee_id': employee.id,
                'check_in': now,
                'in_latitude': lat,
                'in_longitude': lon,
                'is_break': False
            })

            return {
                "success": True,
                "message": "Checked in successfully",
                "attendance_id": rec.id
            }

        if action == 'check_out':
            if open_break:
                return {
                    "success": False,
                    "message": "End break before checking out"
                }

            if not open_work:
                return {
                    "success": False,
                    "message": "No active work session found"
                }

            open_work.write({
                'check_out': now,
                'out_latitude': lat,
                'out_longitude': lon
            })

            return {
                "success": True,
                "message": "Checked out successfully",
                "attendance_id": open_work.id
            }

        if action == 'break_in':
            if not open_work:
                return {
                    "success": False,
                    "message": "Check in before starting break"
                }

            if open_break:
                return {
                    "success": False,
                    "message": "Already on break"
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

            return {
                "success": True,
                "message": "Break started",
                "attendance_id": break_rec.id
            }

        if action == 'break_out':
            if not open_break:
                return {
                    "success": False,
                    "message": "No active break found"
                }

            open_break.write({
                'check_out': now,
                'out_latitude': lat,
                'out_longitude': lon
            })

            work_rec = Attendance.create({
                'employee_id': employee.id,
                'check_in': now,
                'in_latitude': lat,
                'in_longitude': lon,
                'is_break': False
            })

            return {
                "success": True,
                "message": "Break ended, work resumed",
                "attendance_id": work_rec.id
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
    
    @http.route('/mobile/tasks', type='json', auth='user', methods=['POST'], csrf=False)
    def mobile_task_list(self, **kwargs):

        user = request.env.user
        Task = request.env['project.task'].sudo()

        domain = [
            ('user_ids', 'in', user.id)
        ]

        tasks = Task.search(domain, order='id desc')

        result = []
        for task in tasks:
            result.append({
                "id": task.id,
                "name": task.name,
                "project": task.project_id.name if task.project_id else "",
                "stage_id": task.stage_id.id if task.stage_id else None,
                "status": task.stage_id.name if task.stage_id else "",
                "deadline": task.date_deadline,
                "priority": task.priority,
            })

        return {
            "status": 200,
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

        if not start_date or not end_date:
            return {
                "status": 400,
                "message": "start_date and end_date are required"
            }

        user = request.env.user
        employee = request.env['hr.employee'].sudo().search(
            [('user_id', '=', user.id)], limit=1
        )

        if not employee:
            return {
                "status": 400,
                "message": "Employee not linked with user"
            }

        calendar_data = []

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

        events = request.env['event.event'].sudo().search([
            ('date_begin', '>=', start_date),
            ('date_begin', '<=', end_date)
        ])

        for event in events:
            calendar_data.append({
                "type": "event",
                "id": event.id,
                "title": event.name,
                "start": event.date_begin,
                "end": event.date_end,
                "color": "#2196F3",
                "location": event.address_id.name if event.address_id else ""
            })

        return {
            "status": 200,
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

        return {
            "status": 200,
            "uid": user.id,
            "db": request.session.db,
            "username": user.login,
            "auth_info": "Session Active",

            # Partner info
            "name": user.name or "",
            "street": partner.street or "",
            "city": partner.city or "",
            "zip": partner.zip or "",
            "country_id": partner.country_id.code if partner.country_id else "",
            "state_id": partner.state_id.code if partner.state_id else "",

            # Employee info
            "job_title": employee.job_title if employee else "",
            "birthday": employee.birthday.strftime('%d.%m.%Y') if employee and employee.birthday else "",
            "number": employee.private_phone if employee else "",
            "manager": employee.parent_id.name if employee and employee.parent_id else "",

            # Image
            "profile_image_url": self.get_image_url(
                'res.users', user.id, 'image_1920'
            ) or "",
            "image_1920": user.image_1920 or "",
        }

    @http.route('/mobile/profile/update', type='json', auth='user', csrf=False)
    def mobile_profile_update(self, **kwargs):
        user = request.env.user
        if not user:
            return {
                "status": 401,
                "message": "Session expired"
            }

        data = request.get_json_data() or {}
        partner = user.partner_id

        employee = request.env['hr.employee'].sudo().search(
            [('user_id', '=', user.id)], limit=1
        )

        if data.get('name'):
            user.sudo().write({
                'name': data.get('name')
            })

        if data.get('image_1920'):
            user.sudo().write({
                'image_1920': data.get('image_1920')
            })

        employee_vals = {}

        if employee:
            if data.get('birthday'):
                try:
                    employee_vals['birthday'] = fields.Date.from_string(
                        data.get('birthday')
                    )
                except Exception:
                    return {
                        "status": 400,
                        "message": "Invalid birthday format (use YYYY-MM-DD)"
                    }
                
            if data.get('number'):
                employee_vals['private_phone'] = data.get('number')

            if employee_vals:
                employee.sudo().write(employee_vals)

        return {
            "status": 200,
            "message": "Profile updated successfully"
        }



