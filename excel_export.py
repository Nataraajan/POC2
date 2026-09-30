"""Populate the reviewed formula template; no Excel service is needed at runtime.

The template is authored with Artifact Tool. This adapter changes input cells
and calculation caches only, preserving all formulas, formats and validations.
Excel recalculates the full workbook on opening or when an input is edited.
"""

from io import BytesIO
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

import numpy as np
from clab_forecast_engine_v2 import forecast_clab_v2
from segments import segment_key
from curve_model import SYNTHETIC, MANUAL, default_settings, build_curves
import re
from copy import deepcopy

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
ET.register_namespace("", NS)
ET.register_namespace(
    "r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
)
TEMPLATE = Path(__file__).resolve().parent / "templates" / "revenue_model.xlsx"
ROWS = {
    8: "applications",
    11: "originations",
    13: "beginning_gross_clab",
    14: "principal_repaid",
    15: "charge_offs",
    16: "ending_gross_clab",
    18: "beginning_reserve",
    19: "new_provisions",
    20: "ending_reserve",
    21: "net_clab",
    24: "revenue",
    25: "net_revenue",
}


def column(n):
    result = ""
    while n:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def input_cells(snapshot):
    inputs = snapshot["products"]
    out = {
        "E29": snapshot.get("creditfresh_share", 0.8),
        "E6": 2 if snapshot["source"] == SYNTHETIC else 1,
        "E7": next(iter(inputs.values()))["active"]["horizon_months"],
        "E8": snapshot["scenario"],
        "E9": {"Combined": 1, "Line of Credit": 2, "Installment": 3}[snapshot["view"]],
    }
    if snapshot.get("segment_risks"):
        for brand, c, payoff_col in [("CreditFresh Line of Credit","E","H"),("MoneyKey Line of Credit","F","I"),("CreditFresh Installment","J","M"),("MoneyKey Installment","K","N")]:
            out[f"{c}51"] = brand
            out[f"{c}64"] = brand + " default"
            out[f"{payoff_col}64"] = brand + " payoff"
            active=snapshot["segment_risks"][brand]
            historical=snapshot.get("historical_segment_risks",snapshot["segment_risks"])[brand]
            manual=snapshot["curve_settings"][MANUAL][brand]
            synthetic=snapshot["curve_settings"][SYNTHETIC][brand]
            for m,(d,pay) in enumerate(zip(historical["default_shape"],historical["payoff_shape"])):
                out[f"{c}{106+m}"]=d
                out[f"{payoff_col}{106+m}"]=pay
            for r,v in [(52,manual["pd"]/100),(53,manual["default_timing"]),
                        (54,historical["total_default_rate_pct"]/100),(55,synthetic["pd"]/100),
                        (56,synthetic["default_shift_months"]),(57,synthetic["payoff_shift_months"]),
                        (59,manual["payoff_timing"])]:
                out[f"{c}{r}"]=v
    for p, c in [("Line of Credit", "E"), ("Installment", "F")]:
        item = inputs[p]
        a = item["active"]
        values = {
            11: a["monthly_applications_base"],
            12: a["monthly_growth_pct"] / 100,
            13: a["approval_rate_pct"] / 100,
            14: a["avg_loan_size"],
            15: a["annual_yield_pct"] / 100,
            16: a["term_months"],
            17: a["opening_gross_clab"],
            18: 0 if a["opening_age_months"] is None else 1,
            19: a["opening_age_months"] or 0,
            20: item["manual_rate_pct"] / 100,
            21: item["manual_midpoint"],
            22: item["historical_rate_pct"] / 100,
            23: item["historical_midpoint"],
            24: item["stress_pct"] / 100,
            27: 0.55,
        }
        out.update({f"{c}{r}": v for r, v in values.items() if r not in range(20,27)})
        out.update({f"{c}{34+m}": v for m, v in enumerate(a["seasonality_pattern"])})
    return out


def cached_schedules(snapshot):
    """Opening preview values match the app; formulas remain the authority in Excel."""
    builds = {}
    segment_caches = {}
    if snapshot.get("segment_risks"):
        from product_forecast import segment_forecasts, combine
        inputs={p:{**item["active"],"horizon_months":36} for p,item in snapshot["products"].items()}
        segments=segment_forecasts(inputs,snapshot.get("creditfresh_share",.8),snapshot["segment_risks"])
        opening_segments=segment_forecasts({p:{**a,"monthly_applications_base":0} for p,a in inputs.items()},snapshot.get("creditfresh_share",.8),snapshot["segment_risks"])
        for brand,weight,offset in [("CreditFresh",snapshot.get("creditfresh_share",.8),2),("MoneyKey",1-snapshot.get("creditfresh_share",.8),4)]:
            sub={**snapshot,"products":{}}
            sub.pop("segment_risks",None)
            for p,item in snapshot["products"].items():
                base=item["active"]
                sub["products"][p]={**item,"active":{**base,"monthly_applications_base":base["monthly_applications_base"]*weight,"opening_gross_clab":base["opening_gross_clab"]*weight,**{k:v for k,v in snapshot["segment_risks"][segment_key(brand,p)].items() if k in ("total_default_rate_pct", "midpoint_months", "default_shape", "payoff_shape")}}}
                sub["products"][p]["active"].pop("days_to_default",None)
            cache=cached_schedules(sub)
            segment_caches[3+offset]=cache[3];segment_caches[4+offset]=cache[4]

    horizon = next(iter(snapshot["products"].values()))["active"]["horizon_months"]
    for product, item in snapshot["products"].items():
        args = {**item["active"], "horizon_months": 36}
        f = forecast_clab_v2(**args)
        opening = forecast_clab_v2(**{**args, "monthly_applications_base": 0})
        if snapshot.get("segment_risks"):
            f=combine(segments[b][product] for b in segments)
            opening=combine(opening_segments[b][product] for b in segments)
        rows = {r: f[name].to_numpy() for r, name in ROWS.items()}
        rows.update(
            {
                9: np.full(36, args["approval_rate_pct"] / 100),
                10: np.full(36, args["avg_loan_size"]),
                23: np.full(36, args["annual_yield_pct"] / 100),
                27: opening.charge_offs.to_numpy(),
                28: (f.charge_offs - opening.charge_offs).to_numpy(),
                29: opening.principal_repaid.to_numpy(),
                30: (f.principal_repaid - opening.principal_repaid).to_numpy(),
                32: opening.revenue.to_numpy(),
                33: (f.revenue - opening.revenue).to_numpy(),
                34: opening.ending_gross_clab.to_numpy(),
                35: np.zeros(36),
                36: np.zeros(36),
                37: np.zeros(36),
            }
        )
        builds[product] = rows
    selected = list(builds) if snapshot["view"] == "Combined" else [snapshot["view"]]
    combined = {r: sum(builds[p][r] for p in selected) for r in builds[selected[0]]}
    approved = sum(builds[p][8] * builds[p][9] for p in selected)
    combined[9] = np.divide(
        approved, combined[8], out=np.zeros(36), where=combined[8] != 0
    )
    combined[10] = np.divide(
        combined[11], approved, out=np.zeros(36), where=approved != 0
    )
    earning = combined[13] - combined[15]
    combined[23] = np.divide(
        combined[24] * 12, earning, out=np.zeros(36), where=earning != 0
    )
    share = snapshot.get("creditfresh_share", 0.8)
    short = builds["Line of Credit"][24] if "Line of Credit" in selected else np.zeros(36)
    installment = builds["Installment"][24] if "Installment" in selected else np.zeros(36)
    if snapshot.get("segment_risks"):
        cfshort=segments["CreditFresh"]["Line of Credit"].revenue.to_numpy() if "Line of Credit" in selected else np.zeros(36)
        cfins=segments["CreditFresh"]["Installment"].revenue.to_numpy() if "Installment" in selected else np.zeros(36)
        mkshort=segments["MoneyKey"]["Line of Credit"].revenue.to_numpy() if "Line of Credit" in selected else np.zeros(36)
        mkins=segments["MoneyKey"]["Installment"].revenue.to_numpy() if "Installment" in selected else np.zeros(36)
    else:
        cfshort,cfins,mkshort,mkins=short*share,installment*share,short*(1-share),installment*(1-share)
    combined.update({47:cfshort,48:cfins,49:cfshort+cfins,50:mkshort,51:mkins,52:mkshort+mkins,53:short+installment})
    result = {}
    for sheet, rows in [
        (1, combined),
        (3, builds["Line of Credit"]),
        (4, builds["Installment"]),
    ]:
        cells = {
            f"{column(m+7)}{r}": float(v)
            for r, values in rows.items()
            for m, v in enumerate(values)
        }
        for r, values in rows.items():
            if r in [9, 10, 23, 35, 36, 37]:
                continue
            cells[f"E{r}"] = float(
                values[0]
                if r in [13, 18]
                else (
                    values[horizon - 1]
                    if r in [16, 20, 21, 34]
                    else sum(values[:horizon])
                )
            )
        cells["E3"] = snapshot["scenario"]
        result[sheet] = cells
    result.update(segment_caches)
    return result


def _set_value(cell, value, keep_formula=False):
    for child in list(cell):
        if child.tag != f"{{{NS}}}f" or not keep_formula:
            cell.remove(child)
    if isinstance(value, str):
        if keep_formula:
            cell.set("t", "str")
            ET.SubElement(cell, f"{{{NS}}}v").text = value
        else:
            cell.set("t", "inlineStr")
            node = ET.SubElement(cell, f"{{{NS}}}is")
            ET.SubElement(node, f"{{{NS}}}t").text = value
    else:
        cell.attrib.pop("t", None)
        ET.SubElement(cell, f"{{{NS}}}v").text = str(float(value))


def _segment_template(root, idx):
    """Extend the legacy two-brand template to four independent segment inputs."""
    if idx == 2:
        cells = {c.get('r'): c for c in root.iter(f'{{{NS}}}c')}
        rows = {int(r.get('r')): r for r in root.iter(f'{{{NS}}}row')}
        for old, new in [('E','J'), ('F','K'), ('H','M'), ('I','N')]:
            for row in list(range(51,60)) + list(range(64,102)):
                source = cells.get(f'{old}{row}')
                if source is None:
                    continue
                dest = cells.get(f'{new}{row}')
                clone = deepcopy(source)
                clone.set('r', f'{new}{row}')
                formula = clone.find(f'{{{NS}}}f')
                if formula is not None:
                    formula.text = re.sub(r'(\$?)' + old + r'(\$?)(5[2-9])',
                                          lambda m: m[1]+new+m[2]+m[3], formula.text)
                if dest is not None:
                    rows[row].remove(dest)
                rows[row].append(clone)
        # Excel requires cells in column order.
        def col_index(cell):
            value=0
            for ch in re.match(r'[A-Z]+',cell.get('r'))[0]:
                value=value*26+ord(ch)-64
            return value
        for row in rows.values():
            row[:] = sorted(row, key=col_index)
        cells = {c.get('r'): c for c in root.iter(f'{{{NS}}}c')}
        for col, term_col, term in [('E','E',12),('F','E',12),('J','F',24),('K','F',24)]:
            formula = cells[f'{col}58'].find(f'{{{NS}}}f')
            if formula is not None:
                formula.text = f'IF({term_col}16={term},{formula.text},NA())'
        _set_value(cells['C50'], 'Synthetic segment credit assumptions (12/24 months only)')
    if idx in (6,8):
        mapping = {'E':'J','H':'M'} if idx == 6 else {'F':'K','I':'N'}
        # Only credit assumptions move; volumes/yields/terms keep their loan-type cells.
        for formula in root.iter(f'{{{NS}}}f'):
            for old,new in mapping.items():
                formula.text = re.sub(r"('Assumptions'!\$?)"+old+r"(\$?)(5[2-9]|6[5-9]|[7-9][0-9]|10[01])(?![0-9])",
                                      lambda m: m[1]+new+m[2]+m[3], formula.text)
                formula.text = formula.text.replace(f':${old}$101',f':${new}$101')


def _editable_curves(root, idx, snapshot):
    """Upgrade the existing template in the app's dependency-free XML adapter."""
    cells = {c.get('r'): c for c in root.iter(f'{{{NS}}}c')}
    data = root.find(f'{{{NS}}}sheetData')
    rows = {int(r.get('r')): r for r in data}

    def put(address, value, formula=False, style=None):
        row = int(re.search(r'\d+', address)[0])
        if row not in rows:
            rows[row] = ET.SubElement(data, f'{{{NS}}}row', r=str(row))
        if address not in cells:
            cells[address] = ET.SubElement(rows[row], f'{{{NS}}}c', r=address)
        cell = cells[address]
        if style is not None:
            cell.set('s', style)
        _set_value(cell, value if not formula else 0)
        if formula:
            cell.remove(cell.find(f'{{{NS}}}v'))
            ET.SubElement(cell, f'{{{NS}}}f').text = value

    if idx == 2:
        labels = {6: 'Curve source (1 manual, 2 synthetic)', 27: '',
                  50: 'Editable segment curves · fixed 12/24-month terms',
                  52: 'Manual lifetime default', 53: 'Manual default timing',
                  54: 'Original synthetic default', 55: 'Synthetic default override',
                  56: 'Default shift (months)', 57: 'Full-payoff shift (months)',
                  58: 'Applied lifetime default', 59: 'Manual payoff timing',
                  61: 'Synthetic shift: -12 to +12 whole months; 0 = unchanged.',
                  62: 'Positive = later; negative = earlier, floored at MOB 1. Manual shape 1 = even.',
                  63: 'Applied conditional event curves (calculated)',
                  64: 'Months on book',
                  103: 'Original synthetic conditional curves · source, not overrides',
                  104: 'Source: 2,000,000 synthetic loans; observation June 2026.',
                  105: 'Months on book',
                  144: 'Payoff = full closure alongside scheduled amortization. LGD 100%; no recoveries.',
                  145: 'Hypothetical POC segments and credit assumptions; not calibrated to Propel.'}
        for row, label in labels.items():
            put(f'C{row}', label)
        for c in ('E','F'):
            put(c+'27', '')
        pct_style = cells['E52'].get('s')
        num_style = cells['E53'].get('s')
        calculated_style = cells['E58'].get('s')
        for key, c, pay, termcol in [('CreditFresh Line of Credit','E','H','E'),
                                    ('MoneyKey Line of Credit','F','I','E'),
                                    ('CreditFresh Installment','J','M','F'),
                                    ('MoneyKey Installment','K','N','F')]:
            term = snapshot['segment_risks'][key]['term_months']
            for row in (52,54,55):
                cells[c+str(row)].set('s',pct_style)
            cells[c+'54'].set('s',calculated_style)
            for row in (53,56,57,59):
                cells[c+str(row)].set('s',num_style)
            put(c+'58', f'IF(AND({termcol}16={term},OR($E$6=1,$E$6=2)),IF($E$6=2,{c}55,{c}52),NA())', True)
            for age in range(37):
                row = 65 + age
                raw = 106 + age
                put('C'+str(row), age)
                put('C'+str(raw), age)
                for dest, manualrow, synthrow in [(c,53,56),(pay,59,57)]:
                    put(f'{dest}{row}',
                        f'IF($E$6=2,IF(AND({c}${synthrow}=INT({c}${synthrow}),ABS({c}${synthrow})<=12),IF({age}=0,0,INDEX({dest}$106:{dest}$142,MAX(0,MIN(36,{age}-{c}${synthrow}))+1)),NA()),POWER(MIN({age}/{term},1),{c}${manualrow}))',
                        True, calculated_style)
                    put(f'{dest}{raw}', 0, style=calculated_style)
                put(f'{c}105', key+' default')
                put(f'{pay}105', key+' payoff')
        # Replace obsolete midpoint validations with the active credit inputs.
        validations = root.find(f'{{{NS}}}dataValidations')
        if validations is not None:
            for node in list(validations):
                refs = node.get('sqref','').split()
                if any(int(re.search(r'\d+', ref)[0]) >= 50 for ref in refs):
                    validations.remove(node)
        else:
            validations = ET.SubElement(root, f'{{{NS}}}dataValidations')
        for refs, lo, hi in [
            (' '.join(c+str(r) for c in ('E','F','J','K') for r in (52,55)), '0', '.99'),
            (' '.join(c+str(r) for c in ('E','F','J','K') for r in (53,59)), '.25', '4'),
            (' '.join(c+str(r) for c in ('E','F','J','K') for r in (56,57)), '-12', '12')]:
            v = ET.SubElement(validations, f'{{{NS}}}dataValidation',
                              type='whole' if lo == '-12' else 'decimal', operator='between', sqref=refs,
                              showErrorMessage='1', errorStyle='stop', error='Enter a value within the allowed range.')
            ET.SubElement(v, f'{{{NS}}}formula1').text=lo
            ET.SubElement(v, f'{{{NS}}}formula2').text=hi
        validations.set('count',str(len(validations)))
        dimension = root.find(f'{{{NS}}}dimension')
        if dimension is not None:
            dimension.set('ref','A1:N145')
    if idx in (3,4,5,6,7,8):
        # These legacy logistic parameters no longer participate in any cash flow.
        for address in ('C41','E41','C47','E47'):
            if address in cells:
                put(address,'')
    def order(cell):
        n=0
        for ch in re.match('[A-Z]+',cell.get('r'))[0]:
            n=n*26+ord(ch)-64
        return n
    for row in rows.values():
        row[:] = sorted(row,key=order)
    data[:] = sorted(data,key=lambda r:int(r.get('r')))


def export_model(snapshot):
    # The same settings generate both the formula inputs and the preview caches.
    snapshot = deepcopy(snapshot)
    if snapshot["source"] == "Historical vintage":
        snapshot["source"] = SYNTHETIC
    empirical = snapshot.get("historical_segment_risks", snapshot["segment_risks"])
    snapshot.setdefault("curve_settings", {mode: default_settings(mode, empirical) for mode in (SYNTHETIC, MANUAL)})
    snapshot["historical_segment_risks"] = empirical
    snapshot["segment_risks"] = build_curves(snapshot["source"], snapshot["curve_settings"][snapshot["source"]], empirical)
    overrides = input_cells(snapshot)
    caches = cached_schedules(snapshot)
    caches[2] = {}
    for key, c, pay in [('CreditFresh Line of Credit','E','H'),('MoneyKey Line of Credit','F','I'),
                        ('CreditFresh Installment','J','M'),('MoneyKey Installment','K','N')]:
        risk=snapshot['segment_risks'][key]
        caches[2][c+'58']=risk['total_default_rate_pct']/100
        for age in range(37):
            caches[2][f'{c}{65+age}']=risk['default_shape'][age]
            caches[2][f'{pay}{65+age}']=risk['payoff_shape'][age]
    output = BytesIO()
    with zipfile.ZipFile(TEMPLATE) as source, zipfile.ZipFile(
        output, "w", zipfile.ZIP_DEFLATED
    ) as dest:
        for entry in source.infolist():
            data = source.read(entry.filename)
            # Rename template labels and their sheet references together.
            if entry.filename.endswith(".xml"):
                data = data.replace(b"Short-Term", b"Line of Credit")
            if entry.filename.startswith(
                "xl/worksheets/sheet"
            ) and entry.filename.endswith(".xml"):
                idx = int(entry.filename.split("sheet")[-1].split(".")[0])
                root = ET.fromstring(data)
                _segment_template(root, idx)
                _editable_curves(root, idx, snapshot)
                for cell in root.iter(f"{{{NS}}}c"):
                    address = cell.get("r")
                    if idx == 2 and address in overrides:
                        _set_value(cell, overrides[address])
                    elif cell.find(f"{{{NS}}}f") is not None:
                        for v in cell.findall(f"{{{NS}}}v"):
                            cell.remove(v)
                        cell.attrib.pop("t", None)
                        if address in caches.get(idx, {}):
                            _set_value(cell, caches[idx][address], keep_formula=True)
                data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            elif entry.filename == "xl/workbook.xml":
                root = ET.fromstring(data)
                calc = root.find(f"{{{NS}}}calcPr")
                if calc is None:
                    calc = ET.SubElement(root, f"{{{NS}}}calcPr")
                calc.set("calcMode", "auto")
                calc.set("fullCalcOnLoad", "1")
                calc.set("forceFullCalc", "1")
                data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            dest.writestr(entry, data)
    return output.getvalue()
