const shots = [
  {name:'Lob', attempts:28, success:86, score:84, icon:'⌒'},
  {name:'Volley', attempts:44, success:82, score:81, icon:'V'},
  {name:'Bandeja', attempts:19, success:79, score:76, icon:'B'},
  {name:'Víbora', attempts:16, success:69, score:71, icon:'↝'},
  {name:'Chiquita', attempts:13, success:62, score:62, icon:'C'}
];
const defaultMatches = [
  {id:'demo-1',date:'14', month:'JUL', title:'Club match · Court 2', detail:'1h 18m · 214 shots · Complete', score:78},
  {id:'demo-2',date:'05', month:'JUL', title:'League match · Riverside', detail:'1h 32m · 246 shots · Complete', score:75},
  {id:'demo-3',date:'21', month:'JUN', title:'Training match · Court 1', detail:'58m · 177 shots · Complete', score:73},
  {id:'demo-4',date:'08', month:'JUN', title:'Club match · Court 3', detail:'1h 24m · 221 shots · Complete', score:71},
  {id:'demo-5',date:'26', month:'MAY', title:'Friendly · Central Padel', detail:'1h 11m · 198 shots · Complete', score:69},
  {id:'demo-6',date:'10', month:'MAY', title:'Training match · Court 4', detail:'52m · 192 shots · Complete', score:67}
];

const $ = (selector, scope=document) => scope.querySelector(selector);
const $$ = (selector, scope=document) => [...scope.querySelectorAll(selector)];
let currentFile = null;
let calibrationPoints=[];
let liveAnalysisResult=null;
let currentMatchMeta=null;
const analysisApi=window.PADELIQ_ANALYSIS_API||localStorage.getItem('padeliqAnalysisApi')||'';

function routeTo(route){
  $$('.page').forEach(page => page.classList.toggle('active', page.id === route));
  $$('.nav-link').forEach(link => link.classList.toggle('active', link.dataset.route === route));
  $('.sidebar').classList.remove('open');
  $('#menuButton').setAttribute('aria-expanded','false');
  window.scrollTo({top:0,behavior:'smooth'});
  if(route === 'dashboard') requestAnimationFrame(drawHeatmap);
}

$$('[data-route]').forEach(el => el.addEventListener('click', e => { e.preventDefault(); routeTo(el.dataset.route); }));
$('#menuButton').addEventListener('click', () => {
  const open = $('.sidebar').classList.toggle('open');
  $('#menuButton').setAttribute('aria-expanded', String(open));
});

function renderShots(){
  $('#shotList').innerHTML = shots.map(s => `<div class="shot-row"><span class="shot-glyph">${s.icon}</span><div class="shot-info"><strong>${s.name}</strong><small>${s.attempts} attempts · ${s.success}% successful</small><div class="mini-bar"><i style="width:${s.score}%"></i></div></div><div class="shot-score"><strong>${s.score}</strong><small>/ 100</small></div></div>`).join('');
}

function renderMatches(){
  const custom = JSON.parse(localStorage.getItem('padeliqMatches') || '[]');
  const deletedDemo=JSON.parse(localStorage.getItem('padeliqDeletedDemoMatches')||'[]');
  const demo=defaultMatches.filter(match=>!deletedDemo.includes(match.id));
  const matches = [...custom, ...demo];
  $('#matchList').innerHTML = matches.length?matches.map((m,index) => `<article class="match-card"><div class="match-date">${m.date}<small>${m.month}</small></div><div><h3>${m.title}</h3><p>${m.place?`${m.place}${m.court?` · ${m.court}`:''} · `:''}${m.detail}</p></div><div class="match-score"><strong>${m.score}</strong><small>OVERALL</small></div><div class="match-actions"><button class="secondary-button" data-view-match>View report</button><button class="danger-button" data-delete-match="${index<custom.length?`custom:${index}`:`demo:${m.id}`}" aria-label="Delete ${m.title}">Delete</button></div></article>`).join(''):'<div class="panel"><h2>No saved matches</h2><p>Upload a match to create your first report.</p></div>';
  $('#matchesCount').textContent = matches.length;
  $$('[data-view-match]').forEach(button => button.addEventListener('click', () => { routeTo('dashboard'); showToast('Showing the selected match report'); }));
  $$('[data-delete-match]').forEach(button=>button.addEventListener('click',()=>deleteMatch(button.dataset.deleteMatch)));
}

function deleteMatch(target){
  const [type,value]=target.split(':'),custom=JSON.parse(localStorage.getItem('padeliqMatches')||'[]');
  const match=type==='custom'?custom[Number(value)]:defaultMatches.find(item=>item.id===value);if(!match)return;
  if(!window.confirm(`Delete “${match.title}” and its report and score? This cannot be undone.`))return;
  if(type==='custom'){custom.splice(Number(value),1);localStorage.setItem('padeliqMatches',JSON.stringify(custom));}else{const deleted=JSON.parse(localStorage.getItem('padeliqDeletedDemoMatches')||'[]');if(!deleted.includes(value))deleted.push(value);localStorage.setItem('padeliqDeletedDemoMatches',JSON.stringify(deleted));}
  renderMatches();showToast('Match report and score deleted');
}

function renderTrend(){
  const values=[67,69,71,73,75,78], labels=['10 May','26 May','8 Jun','21 Jun','5 Jul','14 Jul'];
  const width=820,height=260,pad=42,min=60,max=82;
  const x=i=>pad+i*(width-pad*2)/(values.length-1), y=v=>height-pad-(v-min)*(height-pad*2)/(max-min);
  const points=values.map((v,i)=>`${x(i)},${y(v)}`).join(' ');
  const grid=[60,65,70,75,80].map(v=>`<line x1="${pad}" y1="${y(v)}" x2="${width-pad}" y2="${y(v)}" stroke="#e2e9e5"/><text x="4" y="${y(v)+4}" fill="#7b8882" font-size="11">${v}</text>`).join('');
  const dots=values.map((v,i)=>`<circle cx="${x(i)}" cy="${y(v)}" r="5" fill="#19a974" stroke="white" stroke-width="3"/><text x="${x(i)}" y="${y(v)-13}" text-anchor="middle" fill="#13251f" font-size="11" font-weight="700">${v}</text><text x="${x(i)}" y="${height-8}" text-anchor="middle" fill="#7b8882" font-size="10">${labels[i]}</text>`).join('');
  $('#trendChart').innerHTML=`<svg viewBox="0 0 ${width} ${height}" aria-hidden="true"><defs><linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#19a974" stop-opacity=".22"/><stop offset="1" stop-color="#19a974" stop-opacity="0"/></linearGradient></defs>${grid}<path d="M ${x(0)} ${height-pad} L ${points.replaceAll(' ',', L ')} L ${x(5)} ${height-pad} Z" fill="url(#area)"/><polyline points="${points}" fill="none" stroke="#19a974" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>${dots}</svg>`;
}

function seededPoints(mode){
  const seeds={all:[[.25,.28,1],[.34,.37,.8],[.28,.53,.72],[.65,.35,.5],[.56,.58,.43],[.22,.72,.36]],attack:[[.27,.24,1],[.39,.28,.7],[.7,.31,.48],[.53,.4,.35]],defence:[[.25,.72,1],[.34,.62,.75],[.65,.76,.55],[.48,.58,.4]]};
  return seeds[mode] || seeds.all;
}

function drawHeatmap(){
  const canvas=$('#courtHeatmap'); if(!canvas || !canvas.offsetParent) return;
  const dpr=window.devicePixelRatio||1,w=560,h=680; canvas.width=w*dpr;canvas.height=h*dpr;
  const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);ctx.clearRect(0,0,w,h);
  const x=55,y=30,cw=450,ch=610;
  ctx.fillStyle='#65b3d8';ctx.fillRect(x,y,cw,ch);
  const points=liveAnalysisResult?.positions?.length
    ? liveAnalysisResult.positions.map(p=>[Math.max(0,Math.min(1,p.x/10)),Math.max(0,Math.min(1,p.y/20)),.48])
    : seededPoints($('#heatmapFilter').value);
  points.forEach(([px,py,intensity])=>{
    const gx=x+px*cw,gy=y+py*ch,r=110*intensity+45;
    const g=ctx.createRadialGradient(gx,gy,5,gx,gy,r);
    g.addColorStop(0,`rgba(240,88,63,${.72*intensity})`);g.addColorStop(.32,`rgba(246,210,82,${.56*intensity})`);g.addColorStop(.66,`rgba(68,208,147,${.3*intensity})`);g.addColorStop(1,'rgba(65,171,195,0)');ctx.fillStyle=g;ctx.fillRect(gx-r,gy-r,r*2,r*2);
  });
  ctx.strokeStyle='rgba(255,255,255,.9)';ctx.lineWidth=3;ctx.strokeRect(x,y,cw,ch);
  ctx.beginPath();ctx.moveTo(x,y+ch/2);ctx.lineTo(x+cw,y+ch/2);ctx.moveTo(x+cw/2,y);ctx.lineTo(x+cw/2,y+ch);ctx.moveTo(x,y+145);ctx.lineTo(x+cw,y+145);ctx.moveTo(x,y+ch-145);ctx.lineTo(x+cw,y+ch-145);ctx.stroke();
  ctx.strokeStyle='#174d6a';ctx.lineWidth=7;ctx.beginPath();ctx.moveTo(x-10,y+ch/2);ctx.lineTo(x+cw+10,y+ch/2);ctx.stroke();
  ctx.fillStyle='rgba(255,255,255,.9)';ctx.font='600 13px DM Sans';ctx.textAlign='center';ctx.fillText('NET',x+cw-28,y+ch/2-11);ctx.fillText('YOUR SIDE',x+cw/2,y+ch-18);
}

$('#heatmapFilter').addEventListener('change',drawHeatmap);
window.addEventListener('resize',drawHeatmap);

const dropZone=$('#dropZone'), videoInput=$('#videoInput');
['dragenter','dragover'].forEach(type=>dropZone.addEventListener(type,e=>{e.preventDefault();dropZone.classList.add('dragging')}));
['dragleave','drop'].forEach(type=>dropZone.addEventListener(type,e=>{e.preventDefault();dropZone.classList.remove('dragging')}));
dropZone.addEventListener('drop',e=>handleFile(e.dataTransfer.files[0]));
videoInput.addEventListener('change',()=>handleFile(videoInput.files[0]));

function handleFile(file){
  if(!file) return;
  if(file.type && !file.type.startsWith('video/')){showToast('Please choose a video file');return;}
  const name=$('#matchName').value.trim(),date=$('#matchDate').value,place=$('#matchPlace').value.trim(),court=$('#matchCourt').value.trim();
  if(!name||!date||!place||!court){showToast('Add the match name, date, place and court number first');videoInput.value='';return;}
  currentMatchMeta={name,date,place,court};
  currentFile=file;$('#selectedFile').textContent=file.name;prepareCalibration(file);setWorkflow(2);
}

function setWorkflow(step){
  ['uploadStep','playerStep','analysisStep','completeStep'].forEach(id=>$('#'+id).classList.add('hidden'));
  const target=step===1?'uploadStep':step===2?'playerStep':step===3?'analysisStep':'completeStep';$('#'+target).classList.remove('hidden');
  $$('.step').forEach(s=>{const n=Number(s.dataset.step);s.classList.toggle('active',n===Math.min(step,3));s.classList.toggle('done',n<step)});
}

$('#startAnalysis').addEventListener('click',()=>{setWorkflow(3);runAnalysis();});

const calibrationLabels=['top-left court corner','top-right court corner','bottom-right court corner','bottom-left court corner','the player you want to analyse'];
function prepareCalibration(file){
  calibrationPoints=[];const video=$('#calibrationVideo');
  if(video.dataset.objectUrl)URL.revokeObjectURL(video.dataset.objectUrl);
  const objectUrl=URL.createObjectURL(file);video.dataset.objectUrl=objectUrl;video.src=objectUrl;video.currentTime=0;updateCalibration();
}
function resizeCalibrationCanvas(){
  const video=$('#calibrationVideo'),canvas=$('#calibrationCanvas');
  if(!video.videoWidth)return;canvas.width=video.videoWidth;canvas.height=video.videoHeight;drawCalibration();
}
function drawCalibration(){
  const canvas=$('#calibrationCanvas'),ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);
  if(calibrationPoints.length>1){ctx.strokeStyle='#65c8ff';ctx.lineWidth=Math.max(3,canvas.width/300);ctx.beginPath();calibrationPoints.slice(0,4).forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));if(calibrationPoints.length>=4)ctx.closePath();ctx.stroke();}
  calibrationPoints.forEach((p,i)=>{ctx.beginPath();ctx.arc(p.x,p.y,Math.max(7,canvas.width/110),0,Math.PI*2);ctx.fillStyle=i===4?'#ffcf5c':'#42b5ef';ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=3;ctx.stroke();ctx.fillStyle='#102a43';ctx.font=`700 ${Math.max(12,canvas.width/70)}px sans-serif`;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(String(i+1),p.x,p.y);});
}
function updateCalibration(){
  const count=calibrationPoints.length;$('#calibrationCount').textContent=`${count} of 5 points selected`;$('#calibrationPrompt').textContent=count<5?`Click ${calibrationLabels[count]}`:'Calibration ready';$('#startAnalysis').disabled=count<5;drawCalibration();
}
$('#calibrationVideo').addEventListener('loadedmetadata',resizeCalibrationCanvas);
$('#calibrationVideo').addEventListener('loadeddata',resizeCalibrationCanvas);
$('#calibrationCanvas').addEventListener('click',event=>{if(calibrationPoints.length>=5)return;const canvas=$('#calibrationCanvas'),rect=canvas.getBoundingClientRect();calibrationPoints.push({x:(event.clientX-rect.left)*canvas.width/rect.width,y:(event.clientY-rect.top)*canvas.height/rect.height});updateCalibration();});
$('#clearCalibration').addEventListener('click',()=>{calibrationPoints=[];updateCalibration();});
$('#removeVideo').addEventListener('click',()=>{if(currentFile&&!window.confirm('Remove this selected video and cancel its analysis?'))return;resetUpload();showToast('Selected video removed');});

function runAnalysis(){
  if(analysisApi){runRealAnalysis();return;}
  let progress=0;
  const stages=[['Preparing your footage…','Checking video quality and identifying court lines.'],['Tracking players…','Following your selected player throughout the match.'],['Mapping court positions…','Building movement paths and the coverage heatmap.'],['Classifying shots…','Grouping shot events and estimating outcomes.'],['Creating your report…','Calculating scores and development insights.']];
  const timer=setInterval(()=>{
    progress=Math.min(100,progress+4);const idx=Math.min(stages.length-1,Math.floor(progress/21));
    $('#analysisProgress').style.width=progress+'%';$('#analysisPercent').textContent=progress+'%';$('#analysisHeading').textContent=stages[idx][0];$('#analysisDescription').textContent=stages[idx][1];
    if(progress===100){clearInterval(timer);setTimeout(()=>{saveAnalysedMatch();setWorkflow(4)},500);}
  },120);
}

async function runRealAnalysis(){
  try{
    $('#analysisHeading').textContent='Uploading match securely…';$('#analysisDescription').textContent='Preparing the video-analysis job.';
    const calibration={corners:calibrationPoints.slice(0,4),player:calibrationPoints[4]};
    const form=new FormData();form.append('video',currentFile);form.append('calibration',JSON.stringify(calibration));
    const response=await fetch(`${analysisApi.replace(/\/$/,'')}/jobs`,{method:'POST',body:form});if(!response.ok)throw new Error(await response.text());
    const job=await response.json();await pollAnalysisJob(job.id);
  }catch(error){$('#analysisHeading').textContent='Analysis could not start';$('#analysisDescription').textContent=error.message;$('#analysisProgress').style.width='0';}
}
async function pollAnalysisJob(jobId){
  const base=analysisApi.replace(/\/$/,'');
  while(true){
    const response=await fetch(`${base}/jobs/${jobId}`);if(!response.ok)throw new Error(await response.text());const job=await response.json();
    $('#analysisProgress').style.width=`${job.progress}%`;$('#analysisPercent').textContent=`${job.progress}%`;$('#analysisHeading').textContent=job.message;
    if(job.status==='complete'){applyRealResult(job.result);saveAnalysedMatch();setWorkflow(4);return;}
    if(job.status==='failed')throw new Error(job.error||'Video analysis failed');await new Promise(resolve=>setTimeout(resolve,2500));
  }
}
function applyRealResult(result){
  liveAnalysisResult=result;const summary=result.summary;$('#distanceStat').textContent=`${Math.round(summary.distance_metres)}m`;$('#distanceContext').textContent=`Average ${summary.average_speed_kmh} km/h · max ${summary.maximum_speed_kmh} km/h`;$('#coverageStat').textContent=`${summary.tracking_coverage_percent}%`;$('#coverageContext').textContent=`${summary.tracked_frames} of ${summary.analysed_frames} sampled frames`;renderAiFeedback(result.ai_feedback);drawHeatmap();
}
function renderAiFeedback(feedback){
  const panel=$('#aiFeedbackPanel');if(!feedback){panel.hidden=true;return;}panel.hidden=false;
  $('#aiSummary').textContent=feedback.summary;$('#aiConfidence').textContent=`${feedback.confidence} confidence`;
  $('#aiStrengths').innerHTML=(feedback.strengths||[]).map(item=>`<li>${escapeHtml(item)}</li>`).join('');
  $('#aiImprovements').innerHTML=(feedback.improvements||[]).map(item=>`<li>${escapeHtml(item)}</li>`).join('');
  $('#aiDisclaimer').textContent=feedback.disclaimer||'';
}
function escapeHtml(value){const element=document.createElement('span');element.textContent=value;return element.innerHTML;}

function saveAnalysedMatch(){
  const selectedDate=currentMatchMeta?.date?new Date(`${currentMatchMeta.date}T12:00:00`):new Date(), months=['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
  const custom=JSON.parse(localStorage.getItem('padeliqMatches')||'[]');
  const summary=liveAnalysisResult?.summary;
  custom.unshift({id:crypto.randomUUID?.()||String(Date.now()),date:String(selectedDate.getDate()).padStart(2,'0'),month:months[selectedDate.getMonth()],isoDate:currentMatchMeta?.date,title:currentMatchMeta?.name||currentFile?.name||'Uploaded match',place:currentMatchMeta?.place||'',court:currentMatchMeta?.court||'',detail:summary?`${Math.round(summary.duration_seconds/60)}m · ${Math.round(summary.distance_metres)}m travelled · Analysis complete`:'1h 18m · Demonstration analysis',score:78,result:liveAnalysisResult||null});
  localStorage.setItem('padeliqMatches',JSON.stringify(custom));renderMatches();
}

$('#viewReport').addEventListener('click',()=>{routeTo('dashboard');showToast('Your latest match has been added');resetUpload();});
function resetUpload(){const video=$('#calibrationVideo');if(video.dataset.objectUrl)URL.revokeObjectURL(video.dataset.objectUrl);video.removeAttribute('src');video.load();currentFile=null;currentMatchMeta=null;videoInput.value='';calibrationPoints=[];$('#startAnalysis').disabled=true;$('#analysisProgress').style.width='0';$('#analysisPercent').textContent='0%';setWorkflow(1);}

function initials(name){return name.trim().split(/\s+/).slice(0,2).map(x=>x[0]?.toUpperCase()).join('')||'P';}
function loadProfile(){
  const profile=JSON.parse(localStorage.getItem('padeliqProfile')||'null'); if(!profile)return;
  $('#profileName').value=profile.name;$('#playingSide').value=profile.side;$('#playerLevel').value=profile.level;applyProfile(profile.name,profile.level);
}
function applyProfile(name,level){const init=initials(name);$('#navName').textContent=name;$('#welcomeName').textContent=name.split(' ')[0];$('#navAvatar').textContent=init;$('#profileAvatar').textContent=init;$('.user-chip small').textContent=level+' player';}
$('#profileForm').addEventListener('submit',async e=>{e.preventDefault();const profile={name:$('#profileName').value.trim(),side:$('#playingSide').value,level:$('#playerLevel').value};localStorage.setItem('padeliqProfile',JSON.stringify(profile));await supabaseClient.auth.updateUser({data:{full_name:profile.name,playing_side:profile.side,level:profile.level}});applyProfile(profile.name,profile.level);$('#profileSaved').textContent='Profile saved';setTimeout(()=>$('#profileSaved').textContent='',2500);});

let toastTimer;function showToast(message){const toast=$('#toast');toast.textContent=message;toast.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>toast.classList.remove('show'),2400);}

const translations={
  en:{navFeatures:'Features',navHow:'How it works',navPricing:'Pricing',signIn:'Sign in',startFree:'Start free',aiCoach:'YOUR AI PADEL COACH',heroTitle:'See your game.<br><em>Play it better.</em>',heroText:'Turn match footage into clear, personalised insights. Understand every shot, movement and decision—then track your progress over time.',analyseFirst:'Analyse your first match',seeHow:'See how it works ↓',noCard:'No card required',freeMatch:'First match free',privacy:'Private by design',builtImprove:'BUILT TO HELP YOU IMPROVE',everythingTitle:'Everything your match can teach you',everythingText:'PadelIQ turns complex match footage into coaching insights you can act on.',shotAnalysis:'Shot analysis',shotAnalysisText:'See success rates and scores for lobs, volleys, bandejas, víboras, smashes and more.',coverageMaps:'Court coverage maps',coverageMapsText:'Understand where you influence play, where gaps appear and how efficiently you recover.',progressTracking:'Progress tracking',progressTrackingText:'Compare matches and see which areas of your game are improving over time.',coachingInsights:'Coaching insights',coachingInsightsText:'Get clear strengths, priorities and practical recommendations for your next session.',simpleProcess:'A SIMPLE PROCESS',threeSteps:'From footage to feedback in three steps',uploadMatch:'Upload your match',uploadMatchText:'Add fixed-camera footage with the full court visible.',selectYourself:'Select yourself',selectYourselfText:'Click your position once so PadelIQ knows who to follow.',getReport:'Get your report',getReportText:'Explore shot scores, heatmaps, movement and improvement priorities.',simplePricing:'SIMPLE PRICING',choosePlan:'Choose how deeply you want to improve',starter:'Starter',forever:'forever',starterDesc:'Try PadelIQ with your first match.',oneAnalysis:'1 match analysis',basicScores:'Basic shot scores',positionHeatmap:'Position heatmap',mostPopular:'MOST POPULAR',perMonth:'per month',playerDesc:'Build a complete picture of your game.',threeAnalyses:'3 analyses each month',allShotScores:'All shot and movement scores',fullHeatmaps:'Full court-coverage heatmaps',longTerm:'Long-term progress tracking',choosePlayer:'Choose Player',proDesc:'For committed players and coaches.',unlimited:'Unlimited analyses',advancedInsights:'Advanced tactical insights',clipsReports:'Shot clips and reports',priority:'Priority processing',choosePro:'Choose Pro',footerText:'Smarter analysis. Better padel.',backHome:'Back to home',authMessage:'Your next level starts with understanding your game.',authQuote:'“The heatmap showed me why I was always late recovering to the net.”',createAccount:'CREATE ACCOUNT',startJourney:'Start your PadelIQ journey',fullName:'Full name',emailAddress:'Email address',password:'Password',passwordHint:'At least 8 characters',agreeTerms:'I agree to the Terms and Privacy Policy',createMyAccount:'Create my account',welcomeBack:'WELCOME BACK',signInAccount:'Sign in to your account',forgotPassword:'Forgot your password?',passwordReset:'PASSWORD RESET',resetPassword:'Reset your password',resetText:'Enter your account email and choose a new password.',newPassword:'New password',updatePassword:'Update password',backSignIn:'Back to sign in',overview:'Overview',analyseMatch:'Analyse match',myMatches:'My matches',progress:'Progress',profile:'Profile',logOut:'Log out'},
  es:{navFeatures:'Funciones',navHow:'Cómo funciona',navPricing:'Precios',signIn:'Iniciar sesión',startFree:'Empezar gratis',aiCoach:'TU ENTRENADOR DE PÁDEL CON IA',heroTitle:'Mira tu juego.<br><em>Juega mejor.</em>',heroText:'Convierte el vídeo de tus partidos en información clara y personalizada. Comprende cada golpe, movimiento y decisión.',analyseFirst:'Analiza tu primer partido',seeHow:'Descubre cómo funciona ↓',noCard:'Sin tarjeta',freeMatch:'Primer partido gratis',privacy:'Privado por diseño',builtImprove:'CREADO PARA AYUDARTE A MEJORAR',everythingTitle:'Todo lo que tu partido puede enseñarte',everythingText:'PadelIQ convierte el vídeo del partido en consejos útiles.',shotAnalysis:'Análisis de golpes',shotAnalysisText:'Consulta porcentajes y puntuaciones de globos, voleas, bandejas, víboras y remates.',coverageMaps:'Mapas de cobertura',coverageMapsText:'Comprende dónde influyes, dónde aparecen huecos y cómo recuperas.',progressTracking:'Seguimiento del progreso',progressTrackingText:'Compara partidos y descubre cómo mejora tu juego.',coachingInsights:'Consejos de entrenamiento',coachingInsightsText:'Recibe fortalezas y prioridades claras para tu próxima sesión.',simpleProcess:'UN PROCESO SENCILLO',threeSteps:'Del vídeo al análisis en tres pasos',uploadMatch:'Sube tu partido',uploadMatchText:'Añade un vídeo fijo con toda la pista visible.',selectYourself:'Selecciónate',selectYourselfText:'Haz clic en tu posición para que PadelIQ pueda seguirte.',getReport:'Recibe tu informe',getReportText:'Explora golpes, mapas de calor, movimiento y prioridades.',simplePricing:'PRECIOS SENCILLOS',choosePlan:'Elige cómo quieres mejorar',starter:'Inicial',forever:'para siempre',starterDesc:'Prueba PadelIQ con tu primer partido.',oneAnalysis:'1 análisis de partido',basicScores:'Puntuaciones básicas',positionHeatmap:'Mapa de posición',mostPopular:'MÁS POPULAR',perMonth:'al mes',playerDesc:'Crea una imagen completa de tu juego.',threeAnalyses:'3 análisis al mes',allShotScores:'Todos los golpes y movimientos',fullHeatmaps:'Mapas completos de cobertura',longTerm:'Progreso a largo plazo',choosePlayer:'Elegir Player',proDesc:'Para jugadores y entrenadores comprometidos.',unlimited:'Análisis ilimitados',advancedInsights:'Información táctica avanzada',clipsReports:'Clips e informes',priority:'Procesamiento prioritario',choosePro:'Elegir Pro',footerText:'Análisis inteligente. Mejor pádel.',backHome:'Volver al inicio',authMessage:'Tu próximo nivel empieza por comprender tu juego.',authQuote:'“El mapa de calor me mostró por qué siempre llegaba tarde a la red.”',createAccount:'CREAR CUENTA',startJourney:'Comienza tu viaje con PadelIQ',fullName:'Nombre completo',emailAddress:'Correo electrónico',password:'Contraseña',passwordHint:'Mínimo 8 caracteres',agreeTerms:'Acepto los Términos y la Política de privacidad',createMyAccount:'Crear mi cuenta',welcomeBack:'BIENVENIDO',signInAccount:'Inicia sesión en tu cuenta',forgotPassword:'¿Olvidaste tu contraseña?',passwordReset:'RESTABLECER CONTRASEÑA',resetPassword:'Restablece tu contraseña',resetText:'Introduce tu correo y una nueva contraseña.',newPassword:'Nueva contraseña',updatePassword:'Actualizar contraseña',backSignIn:'Volver al inicio de sesión',overview:'Resumen',analyseMatch:'Analizar partido',myMatches:'Mis partidos',progress:'Progreso',profile:'Perfil',logOut:'Cerrar sesión'},
  fr:{navFeatures:'Fonctionnalités',navHow:'Fonctionnement',navPricing:'Tarifs',signIn:'Connexion',startFree:'Commencer gratuitement',aiCoach:'VOTRE COACH DE PADEL IA',heroTitle:'Voyez votre jeu.<br><em>Jouez mieux.</em>',heroText:'Transformez vos vidéos de match en conseils clairs et personnalisés.',analyseFirst:'Analyser mon premier match',seeHow:'Voir comment ça marche ↓',noCard:'Sans carte bancaire',freeMatch:'Premier match gratuit',privacy:'Confidentiel par conception',builtImprove:'CONÇU POUR VOUS FAIRE PROGRESSER',everythingTitle:'Tout ce que votre match peut vous apprendre',everythingText:'PadelIQ transforme vos vidéos en conseils exploitables.',shotAnalysis:'Analyse des coups',coverageMaps:'Cartes de couverture',progressTracking:'Suivi des progrès',coachingInsights:'Conseils personnalisés',simpleProcess:'UN PROCESSUS SIMPLE',threeSteps:'De la vidéo au retour en trois étapes',uploadMatch:'Importez votre match',selectYourself:'Sélectionnez-vous',getReport:'Recevez votre rapport',simplePricing:'TARIFS SIMPLES',choosePlan:'Choisissez votre niveau de progression',starter:'Découverte',forever:'pour toujours',mostPopular:'LE PLUS POPULAIRE',perMonth:'par mois',choosePlayer:'Choisir Player',choosePro:'Choisir Pro',footerText:'Une analyse plus intelligente. Un meilleur padel.',backHome:'Retour à l’accueil',authMessage:'Votre prochain niveau commence par la compréhension de votre jeu.',createAccount:'CRÉER UN COMPTE',startJourney:'Commencez avec PadelIQ',fullName:'Nom complet',emailAddress:'Adresse e-mail',password:'Mot de passe',passwordHint:'8 caractères minimum',agreeTerms:'J’accepte les conditions et la politique de confidentialité',createMyAccount:'Créer mon compte',welcomeBack:'BON RETOUR',signInAccount:'Connectez-vous à votre compte',forgotPassword:'Mot de passe oublié ?',passwordReset:'RÉINITIALISATION',resetPassword:'Réinitialisez votre mot de passe',newPassword:'Nouveau mot de passe',updatePassword:'Mettre à jour',backSignIn:'Retour à la connexion',overview:'Vue d’ensemble',analyseMatch:'Analyser un match',myMatches:'Mes matchs',progress:'Progression',profile:'Profil',logOut:'Déconnexion'},
  de:{navFeatures:'Funktionen',navHow:'So funktioniert es',navPricing:'Preise',signIn:'Anmelden',startFree:'Kostenlos starten',aiCoach:'DEIN KI-PADEL-COACH',heroTitle:'Sieh dein Spiel.<br><em>Spiele besser.</em>',heroText:'Verwandle Matchvideos in klare, persönliche Erkenntnisse.',analyseFirst:'Erstes Match analysieren',seeHow:'So funktioniert es ↓',noCard:'Keine Karte erforderlich',freeMatch:'Erstes Match kostenlos',privacy:'Privat entwickelt',builtImprove:'ENTWICKELT, UM DICH ZU VERBESSERN',everythingTitle:'Alles, was dein Match dir zeigen kann',shotAnalysis:'Schlaganalyse',coverageMaps:'Platzabdeckung',progressTracking:'Fortschritt verfolgen',coachingInsights:'Coaching-Tipps',simpleProcess:'EIN EINFACHER ABLAUF',threeSteps:'In drei Schritten vom Video zum Feedback',uploadMatch:'Match hochladen',selectYourself:'Wähle dich aus',getReport:'Bericht erhalten',simplePricing:'EINFACHE PREISE',choosePlan:'Wähle deinen Weg zur Verbesserung',starter:'Starter',forever:'dauerhaft',mostPopular:'AM BELIEBTESTEN',perMonth:'pro Monat',choosePlayer:'Player wählen',choosePro:'Pro wählen',footerText:'Intelligentere Analyse. Besseres Padel.',backHome:'Zur Startseite',authMessage:'Dein nächstes Level beginnt damit, dein Spiel zu verstehen.',createAccount:'KONTO ERSTELLEN',startJourney:'Starte mit PadelIQ',fullName:'Vollständiger Name',emailAddress:'E-Mail-Adresse',password:'Passwort',passwordHint:'Mindestens 8 Zeichen',agreeTerms:'Ich stimme Bedingungen und Datenschutz zu',createMyAccount:'Konto erstellen',welcomeBack:'WILLKOMMEN ZURÜCK',signInAccount:'Bei deinem Konto anmelden',forgotPassword:'Passwort vergessen?',passwordReset:'PASSWORT ZURÜCKSETZEN',resetPassword:'Passwort zurücksetzen',newPassword:'Neues Passwort',updatePassword:'Passwort aktualisieren',backSignIn:'Zurück zur Anmeldung',overview:'Übersicht',analyseMatch:'Match analysieren',myMatches:'Meine Matches',progress:'Fortschritt',profile:'Profil',logOut:'Abmelden'},
  it:{navFeatures:'Funzioni',navHow:'Come funziona',navPricing:'Prezzi',signIn:'Accedi',startFree:'Inizia gratis',aiCoach:'IL TUO COACH DI PADEL IA',heroTitle:'Guarda il tuo gioco.<br><em>Gioca meglio.</em>',heroText:'Trasforma i filmati delle partite in indicazioni chiare e personalizzate.',analyseFirst:'Analizza la prima partita',seeHow:'Scopri come funziona ↓',noCard:'Nessuna carta richiesta',freeMatch:'Prima partita gratis',privacy:'Privacy integrata',builtImprove:'CREATO PER FARTI MIGLIORARE',everythingTitle:'Tutto ciò che la partita può insegnarti',shotAnalysis:'Analisi dei colpi',coverageMaps:'Mappe di copertura',progressTracking:'Progressi nel tempo',coachingInsights:'Consigli di coaching',simpleProcess:'UN PROCESSO SEMPLICE',threeSteps:'Dal video al feedback in tre passaggi',uploadMatch:'Carica la partita',selectYourself:'Seleziona te stesso',getReport:'Ricevi il report',simplePricing:'PREZZI SEMPLICI',choosePlan:'Scegli come migliorare',starter:'Base',forever:'per sempre',mostPopular:'PIÙ POPOLARE',perMonth:'al mese',choosePlayer:'Scegli Player',choosePro:'Scegli Pro',footerText:'Analisi più intelligente. Padel migliore.',backHome:'Torna alla home',authMessage:'Il tuo prossimo livello inizia comprendendo il tuo gioco.',createAccount:'CREA ACCOUNT',startJourney:'Inizia con PadelIQ',fullName:'Nome completo',emailAddress:'Indirizzo email',password:'Password',passwordHint:'Almeno 8 caratteri',agreeTerms:'Accetto i Termini e la Privacy Policy',createMyAccount:'Crea il mio account',welcomeBack:'BENTORNATO',signInAccount:'Accedi al tuo account',forgotPassword:'Password dimenticata?',passwordReset:'REIMPOSTA PASSWORD',resetPassword:'Reimposta la password',newPassword:'Nuova password',updatePassword:'Aggiorna password',backSignIn:'Torna all’accesso',overview:'Panoramica',analyseMatch:'Analizza partita',myMatches:'Le mie partite',progress:'Progressi',profile:'Profilo',logOut:'Esci'},
  nl:{navFeatures:'Functies',navHow:'Hoe het werkt',navPricing:'Prijzen',signIn:'Inloggen',startFree:'Gratis beginnen',aiCoach:'JOUW AI-PADELCOACH',heroTitle:'Zie je spel.<br><em>Speel beter.</em>',heroText:'Zet wedstrijdbeelden om in duidelijke, persoonlijke inzichten.',analyseFirst:'Analyseer je eerste wedstrijd',seeHow:'Bekijk hoe het werkt ↓',noCard:'Geen kaart nodig',freeMatch:'Eerste wedstrijd gratis',privacy:'Privacy voorop',builtImprove:'GEMAAKT OM JE TE HELPEN VERBETEREN',everythingTitle:'Alles wat je wedstrijd je kan leren',shotAnalysis:'Slaganalyse',coverageMaps:'Dekkingskaarten',progressTracking:'Voortgang volgen',coachingInsights:'Coachinginzichten',simpleProcess:'EEN EENVOUDIG PROCES',threeSteps:'Van beelden naar feedback in drie stappen',uploadMatch:'Upload je wedstrijd',selectYourself:'Selecteer jezelf',getReport:'Ontvang je rapport',simplePricing:'EENVOUDIGE PRIJZEN',choosePlan:'Kies hoe ver je wilt verbeteren',starter:'Starter',forever:'voor altijd',mostPopular:'MEEST POPULAIR',perMonth:'per maand',choosePlayer:'Kies Player',choosePro:'Kies Pro',footerText:'Slimmere analyse. Beter padel.',backHome:'Terug naar home',authMessage:'Je volgende niveau begint met inzicht in je spel.',createAccount:'ACCOUNT MAKEN',startJourney:'Begin met PadelIQ',fullName:'Volledige naam',emailAddress:'E-mailadres',password:'Wachtwoord',passwordHint:'Minimaal 8 tekens',agreeTerms:'Ik ga akkoord met de voorwaarden en het privacybeleid',createMyAccount:'Account maken',welcomeBack:'WELKOM TERUG',signInAccount:'Log in op je account',forgotPassword:'Wachtwoord vergeten?',passwordReset:'WACHTWOORD HERSTELLEN',resetPassword:'Herstel je wachtwoord',newPassword:'Nieuw wachtwoord',updatePassword:'Wachtwoord bijwerken',backSignIn:'Terug naar inloggen',overview:'Overzicht',analyseMatch:'Wedstrijd analyseren',myMatches:'Mijn wedstrijden',progress:'Voortgang',profile:'Profiel',logOut:'Uitloggen'},
  el:{navFeatures:'Λειτουργίες',navHow:'Πώς λειτουργεί',navPricing:'Τιμές',signIn:'Σύνδεση',startFree:'Ξεκινήστε δωρεάν',aiCoach:'Ο AI ΠΡΟΠΟΝΗΤΗΣ PADEL ΣΑΣ',heroTitle:'Δείτε το παιχνίδι σας.<br><em>Παίξτε καλύτερα.</em>',heroText:'Μετατρέψτε το βίντεο του αγώνα σε σαφείς, εξατομικευμένες πληροφορίες.',analyseFirst:'Αναλύστε τον πρώτο αγώνα',seeHow:'Δείτε πώς λειτουργεί ↓',noCard:'Δεν απαιτείται κάρτα',freeMatch:'Πρώτος αγώνας δωρεάν',privacy:'Απόρρητο από τον σχεδιασμό',builtImprove:'ΣΧΕΔΙΑΣΜΕΝΟ ΓΙΑ ΒΕΛΤΙΩΣΗ',everythingTitle:'Όλα όσα μπορεί να σας μάθει ο αγώνας',shotAnalysis:'Ανάλυση χτυπημάτων',coverageMaps:'Χάρτες κάλυψης',progressTracking:'Παρακολούθηση προόδου',coachingInsights:'Συμβουλές προπόνησης',simpleProcess:'ΜΙΑ ΑΠΛΗ ΔΙΑΔΙΚΑΣΙΑ',threeSteps:'Από το βίντεο στην ανατροφοδότηση σε τρία βήματα',uploadMatch:'Ανεβάστε τον αγώνα',selectYourself:'Επιλέξτε τον εαυτό σας',getReport:'Λάβετε την αναφορά',simplePricing:'ΑΠΛΕΣ ΤΙΜΕΣ',choosePlan:'Επιλέξτε πώς θέλετε να βελτιωθείτε',starter:'Αρχικό',forever:'για πάντα',mostPopular:'ΔΗΜΟΦΙΛΕΣΤΕΡΟ',perMonth:'τον μήνα',choosePlayer:'Επιλογή Player',choosePro:'Επιλογή Pro',footerText:'Εξυπνότερη ανάλυση. Καλύτερο padel.',backHome:'Πίσω στην αρχική',authMessage:'Το επόμενο επίπεδό σας ξεκινά με την κατανόηση του παιχνιδιού σας.',createAccount:'ΔΗΜΙΟΥΡΓΙΑ ΛΟΓΑΡΙΑΣΜΟΥ',startJourney:'Ξεκινήστε με το PadelIQ',fullName:'Ονοματεπώνυμο',emailAddress:'Email',password:'Κωδικός',passwordHint:'Τουλάχιστον 8 χαρακτήρες',agreeTerms:'Συμφωνώ με τους Όρους και την Πολιτική Απορρήτου',createMyAccount:'Δημιουργία λογαριασμού',welcomeBack:'ΚΑΛΩΣ ΗΡΘΑΤΕ',signInAccount:'Συνδεθείτε στον λογαριασμό σας',forgotPassword:'Ξεχάσατε τον κωδικό;',passwordReset:'ΕΠΑΝΑΦΟΡΑ ΚΩΔΙΚΟΥ',resetPassword:'Επαναφορά κωδικού',newPassword:'Νέος κωδικός',updatePassword:'Ενημέρωση κωδικού',backSignIn:'Πίσω στη σύνδεση',overview:'Επισκόπηση',analyseMatch:'Ανάλυση αγώνα',myMatches:'Οι αγώνες μου',progress:'Πρόοδος',profile:'Προφίλ',logOut:'Αποσύνδεση'}
};

function applyLanguage(language){
  const lang=translations[language]?language:'en', dict=translations[lang], fallback=translations.en;
  document.documentElement.lang=lang;localStorage.setItem('padeliqLanguage',lang);
  $$('.language-select').forEach(select=>select.value=lang);
  $$('[data-i18n]').forEach(el=>{if(el.children.length)return;const value=dict[el.dataset.i18n]||fallback[el.dataset.i18n];if(value)el.textContent=value;});
  $$('[data-i18n-html]').forEach(el=>{const value=dict[el.dataset.i18nHtml]||fallback[el.dataset.i18nHtml];if(value)el.innerHTML=value;});
}
$$('.language-select').forEach(select=>select.addEventListener('change',()=>applyLanguage(select.value)));

const supabaseClient=window.supabase.createClient('https://lsotekuhbrdtfmlyindd.supabase.co','sb_publishable_p7OOWIbybkMLLfRB1w8t6A_UxIXyarb');
function showLanding(){ $('#landing').classList.remove('hidden');$('#authView').classList.add('hidden');$('#appShell').classList.add('hidden');window.scrollTo(0,0); }
function showAuth(mode='signup'){$('#landing').classList.add('hidden');$('#appShell').classList.add('hidden');$('#authView').classList.remove('hidden');switchAuth(mode);window.scrollTo(0,0);}
function switchAuth(mode){['signup','signin','reset','recovery'].forEach(name=>$('#'+name+'Form').classList.toggle('hidden',name!==mode));}
function showApp(user){
  $('#landing').classList.add('hidden');$('#authView').classList.add('hidden');$('#appShell').classList.remove('hidden');
  if(user){const name=user.user_metadata?.full_name||user.email.split('@')[0];$('#profileEmail').value=user.email;const profile=JSON.parse(localStorage.getItem('padeliqProfile')||'null');if(!profile){$('#profileName').value=name;applyProfile(name,user.user_metadata?.level||'Competitive');}}
  routeTo('dashboard');setTimeout(drawHeatmap,30);
}
$$('[data-auth]').forEach(button=>button.addEventListener('click',()=>showAuth(button.dataset.auth)));
$$('[data-switch-auth]').forEach(button=>button.addEventListener('click',()=>switchAuth(button.dataset.switchAuth)));
$('#backHome').addEventListener('click',showLanding);
$('#logoutButton').addEventListener('click',async()=>{await supabaseClient.auth.signOut();showLanding();});
$('#deleteAllMatches').addEventListener('click',()=>{if(!window.confirm('Delete every saved match report, score and analysis result from this browser? This cannot be undone.'))return;localStorage.removeItem('padeliqMatches');localStorage.setItem('padeliqDeletedDemoMatches',JSON.stringify(defaultMatches.map(match=>match.id)));liveAnalysisResult=null;renderMatches();$('#distanceStat').textContent='—';$('#distanceContext').textContent='Available after real tracking';$('#coverageStat').textContent='—';$('#coverageContext').textContent='Measured frames successfully tracked';drawHeatmap();showToast('All match data deleted');});

$('#signupForm').addEventListener('submit',async e=>{
  e.preventDefault();const email=$('#signupEmail').value.trim().toLowerCase(),password=$('#signupPassword').value,name=$('#signupName').value.trim();
  const redirectTo=location.origin==='null'?undefined:location.origin;
  const {data,error}=await supabaseClient.auth.signUp({email,password,options:{data:{full_name:name,playing_side:'Left',level:'Competitive'},emailRedirectTo:redirectTo}});
  if(error){$('#signupError').textContent=error.message;return;}
  localStorage.setItem('padeliqProfile',JSON.stringify({name,side:'Left',level:'Competitive'}));loadProfile();
  if(data.session)showApp(data.user);else{$('#signupError').classList.add('auth-success');$('#signupError').textContent='Account created. Check your email to confirm your address, then sign in.';}
});
$('#signinForm').addEventListener('submit',async e=>{
  e.preventDefault();const email=$('#signinEmail').value.trim().toLowerCase(),password=$('#signinPassword').value;
  const {data,error}=await supabaseClient.auth.signInWithPassword({email,password});
  if(error){$('#signinError').textContent=error.message;return;}loadProfile();showApp(data.user);
});
$('#resetForm').addEventListener('submit',async e=>{
  e.preventDefault();const email=$('#resetEmail').value.trim().toLowerCase(),redirectTo=location.origin==='null'?undefined:location.origin;
  const {error}=await supabaseClient.auth.resetPasswordForEmail(email,redirectTo?{redirectTo}:undefined);
  if(error){$('#resetError').textContent=error.message;return;}$('#resetError').classList.add('auth-success');$('#resetError').textContent='Reset link sent. Check your email.';
});
$('#recoveryForm').addEventListener('submit',async e=>{e.preventDefault();const {error}=await supabaseClient.auth.updateUser({password:$('#recoveryPassword').value});if(error){$('#recoveryError').textContent=error.message;return;}$('#recoveryError').classList.add('auth-success');$('#recoveryError').textContent='Password updated successfully.';setTimeout(async()=>{const {data}=await supabaseClient.auth.getUser();showApp(data.user);},900);});

renderShots();renderMatches();renderTrend();loadProfile();applyLanguage(localStorage.getItem('padeliqLanguage')||'en');
$('#matchDate').valueAsDate=new Date();
supabaseClient.auth.onAuthStateChange((event,session)=>{if(event==='PASSWORD_RECOVERY'){showAuth('recovery');}else if(event==='SIGNED_IN'&&session?.user){showApp(session.user);}});
supabaseClient.auth.getSession().then(({data})=>{if(data.session?.user)showApp(data.session.user);else showLanding();});
