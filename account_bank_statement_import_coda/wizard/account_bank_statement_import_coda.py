# -*- coding: utf-8 -*-
##############################################################################
#
#     This file is part of account_bank_statement_import_coda,
#     an Odoo module.
#
#     Copyright (c) 2015 ACSONE SA/NV (<http://acsone.eu>)
#
#     account_bank_statement_import_coda is free software:
#     you can redistribute it and/or modify it under the terms of the GNU
#     Affero General Public License as published by the Free Software
#     Foundation,either version 3 of the License, or (at your option) any
#     later version.
#
#     account_bank_statement_import_coda is distributed
#     in the hope that it will be useful, but WITHOUT ANY WARRANTY; without
#     even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
#     PURPOSE.  See the GNU Affero General Public License for more details.
#
#     You should have received a copy of the GNU Affero General Public License
#     along with account_bank_statement_import_coda.
#     If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

import re
import datetime
import logging
from dateutil import parser as date_parser

from openerp import api, models
from openerp.tools.translate import _
from openerp.exceptions import Warning

_logger = logging.getLogger(__name__)

try:
    from coda.parser import Parser
    from coda.statement import AmountSign, MovementRecordType
except ImportError:
    _logger.error(
        "CODA parser unavailable because the `pycoda` Python library cannot "
        "be found. It can be downloaded and installed from "
        "`https://pypi.python.org/pypi/pycoda`.")
    Parser = None


class account_bank_statement_import(models.TransientModel):
    _inherit = 'account.bank.statement.import'

    def _check_coda(self, data_file):
        if Parser is None:
            return False
        try:
            # Matches the first 24 characters of a CODA file, as defined by
            # the febelfin specifications
            return re.match(r'0{5}\d{9}05[ D] {7}', data_file) is not None
        except:
            return False

    @api.model
    def _parse_file(self, data_file):
        if not self._check_coda(data_file):
            return super(account_bank_statement_import, self)._parse_file(
                data_file)
        vals_bank_statements = []
        try:
            statements = Parser().parse(data_file)
            for statement in statements:
                vals_bank_statements.append(
                    self.get_st_vals(statement))
        except Exception, e:
            _logger.exception('Error when parsing coda file')
            raise Warning(
                _("The following problem occurred during import. "
                  "The file might not be valid.\n\n %s" % e.message))

        acc_number = None
        currency = None
        if statements:
            acc_number = statements[0].acc_number
            currency = statement.currency
        return currency, acc_number, vals_bank_statements

    def get_st_vals(self, statement):
        """
        This method return a dict of vals that can be passed to
        create method of statement.
        :return: dict of vals that represent additional infos for the statement
            found in the file.
            {
             'name': paper_seq_number
             'balance_start': balance_start,
             'balance_end_real': balance_end_real,
             'transactions': transactions
            }
        """
        balance_start = statement.old_balance
        if statement.old_balance_amount_sign == AmountSign.DEBIT:
            balance_start = - balance_start
        balance_end_real = statement.new_balance
        if statement.new_balance_amount_sign == AmountSign.DEBIT:
            balance_end_real = - balance_end_real
        transactions = []
        vals = {'balance_start': balance_start,
                'balance_end_real': balance_end_real,
                'date': statement.creation_date,
                'transactions': transactions
                }
        name = statement.paper_seq_number
        if name:
            year = ""
            if statement.creation_date:
                parsed_date = date_parser.parse(statement.creation_date)
                year = "%s/" % parsed_date.year
            vals.update({
                'name': "%s%s" % (year, statement.paper_seq_number),
            })

        globalisation_dict = dict([
            (st.ref_move, st) for st in statement.movements
            if st.type == MovementRecordType.GLOBALISATION])
        for sequence, line in enumerate(
                filter(lambda l: l.type != MovementRecordType.GLOBALISATION,
                       statement.movements)
                ):
            if line.type != MovementRecordType.GLOBALISATION:
                info = self.get_st_line_vals(line,
                                             globalisation_dict)
                info['sequence'] = sequence
                transactions.append(info)
        coda_notes = []
        for line in statement.informations:
            coda_notes.append(self.get_st_information_msg(line))
        for line in statement.free_comunications:
            coda_notes.append(self.get_st_free_communication_msg(line))
        return vals

    def get_st_free_communication_msg(self, line):
        """ This method returns formatted informations from 'free
        commiunication' line
        """
        return ('Communication with Ref. ' + line.ref +
                '\n' +
                'Communication: ' + line.communication +
                '\n')

    def get_st_information_msg(self, line):
        """ This method returns formatted informations from an information
        line
        """
        return ('Information with Ref. ' + line.ref +
                '\n' +
                'Communication: ' + line.communication +
                '\n')

    def get_st_line_note_msg(self, line):
        """This method returns a formatted note from line information
        """
        note = []
        if line.counterparty_name:
            note.append(_('Counter Party') + ': ' +
                        line.counterparty_name)
        if line.counterparty_number:
            note.append(_('Counter Party Account') + ': ' +
                        line.counterparty_number)
        if line.counterparty_address:
            note.append(_('Counter Party Address') + ': ' +
                        line.counterparty_address)
        if line.communication:
            note.append(_('Communication') + ': ' +
                        line.communication)
        return note and '\n'.join(note) or None

    def get_st_line_name(self, line, globalisation_dict):
        """
        This method must return a valid name for the statement line
        The name is the statement communication if exists or
        the communication of the related globalisation line if exists or
        '/'
        """
        name = line.communication
        if not name and line.ref_move in globalisation_dict:
            name = globalisation_dict[line.ref_move].communication
        return name or '/'

    def get_st_line_vals(self, line, globalisation_dict):
        """
        This method must return a dict of vals that can be passed to create
        method of statement line in order to record it. It is the
        responsibility of every parser to give this dict of vals,
        so each one can implement his own way of recording the lines.
            :param:  line: a dict of vals that represent a line of
            result_row_list
            :return: dict of values to give to the create method of
            statement line,
                     it MUST contain at least:
                {
                    'name':value,
                    'date':value,
                    'amount':value,
                    'ref':value,
                }
        """
        amount = line.transaction_amount
        if line.transaction_amount_sign == AmountSign.DEBIT:
            amount = - amount
        return {'name': self.get_st_line_name(line, globalisation_dict),
                'date': line.entry_date or datetime.datetime.now().date(),
                'amount': amount,
                'ref': line.ref,
                'partner_name': line.counterparty_name or None,
                'account_number': line.counterparty_number or None,
                'note': self.get_st_line_note_msg(line),
                'unique_import_id': line.ref + line.transaction_ref,
                }
