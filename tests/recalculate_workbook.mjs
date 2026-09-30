import fs from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
const workUrl=pathToFileURL(path.resolve(process.argv[2])+path.sep);
import {FileBlob,SpreadsheetFile} from '@oai/artifact-tool';
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(new URL('forecast-check.xlsx',workUrl).pathname.replace(/^\/([A-Z]:)/,'$1')));
console.log((await wb.inspect({kind:'sheet',include:'id,name',maxChars:2000})).ndjson);
wb.recalculate();
console.log((await wb.inspect({kind:'table',range:"'Revenue model'!E24:I25",include:'values,formulas',tableMaxRows:2,tableMaxCols:5,maxChars:1500})).ndjson);
const cases=JSON.parse(await fs.readFile(new URL('excel-cases.json',workUrl),'utf8'));
const a=wb.worksheets.getItem('Assumptions');
const out=wb.worksheets.getItem('Revenue model');
const mapping={'CreditFresh Line of Credit':'E','MoneyKey Line of Credit':'F','CreditFresh Installment':'J','MoneyKey Installment':'K'};
const metrics={11:'originations',13:'beginning_gross_clab',14:'principal_repaid',15:'charge_offs',16:'ending_gross_clab',18:'beginning_reserve',19:'new_provisions',20:'ending_reserve',21:'net_clab',24:'revenue',25:'net_revenue'};
for(const c of cases){
  a.getRange('E6').values=[[c.source==='Synthetic vintage'?2:1]];
  a.getRange('E29').values=[[c.mix]];
  a.getRange('E9').values=[[{'Combined':1,'Line of Credit':2,'Installment':3}[c.view]]];
  for(const [key,col] of Object.entries(mapping)){
    const s=c.settings[key];
    const rows=c.source==='Synthetic vintage'?[55,56,57]:[52,53,59];
    [s.pd/100,s.default_timing,s.payoff_timing].forEach((v,i)=>a.getRange(col+rows[i]).values=[[v]]);
  }
  wb.recalculate();
  let maxError=0;
  for(const [row,metric] of Object.entries(metrics)){
    const values=out.getRange(`G${row}:AD${row}`).values[0];
    values.forEach((v,i)=>{
      const expected=c.expected[metric][i];
      if(typeof v!=='number'||!Number.isFinite(v)||Math.abs(v-expected)>Math.max(.01,Math.abs(expected)*1e-9))
        throw Error(`${c.name} ${metric} month ${i+1}: Excel ${v}, Python ${expected}`);
      maxError=Math.max(maxError,Math.abs(v-expected));
    });
  }
  console.log(c.name+' PASS max dollar error '+maxError);
}
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!',options:{useRegex:true,maxResults:15},maxChars:2000});
console.log(errors.ndjson);
for(const [name,range,file] of [['Assumptions','C50:N62','excel-controls.png'],['Assumptions','C63:N72','excel-curves.png'],['Revenue model','C5:L25','excel-forecast.png']]){
  const img=await wb.render({sheetName:name,range,scale:1.5,format:'png'});
  await fs.writeFile(new URL(file,workUrl),new Uint8Array(await img.arrayBuffer()));
}
