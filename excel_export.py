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
        "E6": 2 if snapshot["source"] == "Historical vintage" else 1,
        "E7": next(iter(inputs.values()))["active"]["horizon_months"],
        "E8": snapshot["scenario"],
        "E9": {"Combined": 1, "Short-Term": 2, "Installment": 3}[snapshot["view"]],
    }
    for p, c in [("Short-Term", "E"), ("Installment", "F")]:
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
        out.update({f"{c}{r}": v for r, v in values.items()})
        out.update({f"{c}{34+m}": v for m, v in enumerate(a["seasonality_pattern"])})
    return out


def cached_schedules(snapshot):
    """Opening preview values match the app; formulas remain the authority in Excel."""
    builds = {}
    horizon = next(iter(snapshot["products"].values()))["active"]["horizon_months"]
    for product, item in snapshot["products"].items():
        args = {**item["active"], "horizon_months": 36}
        f = forecast_clab_v2(**args)
        opening = forecast_clab_v2(**{**args, "monthly_applications_base": 0})
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
    short = builds["Short-Term"][24] if "Short-Term" in selected else np.zeros(36)
    installment = builds["Installment"][24] if "Installment" in selected else np.zeros(36)
    combined.update({47:short*share, 48:installment*share, 49:(short+installment)*share,
                     50:short*(1-share), 51:installment*(1-share), 52:(short+installment)*(1-share), 53:short+installment})
    result = {}
    for sheet, rows in [
        (1, combined),
        (3, builds["Short-Term"]),
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


def export_model(snapshot):
    overrides = input_cells(snapshot)
    caches = cached_schedules(snapshot)
    output = BytesIO()
    with zipfile.ZipFile(TEMPLATE) as source, zipfile.ZipFile(
        output, "w", zipfile.ZIP_DEFLATED
    ) as dest:
        for entry in source.infolist():
            data = source.read(entry.filename)
            if entry.filename.startswith(
                "xl/worksheets/sheet"
            ) and entry.filename.endswith(".xml"):
                idx = int(entry.filename.split("sheet")[-1].split(".")[0])
                root = ET.fromstring(data)
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
