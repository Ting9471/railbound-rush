import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import "./styles.css";
import { LANES, PLAYER_Z, GROUND_Y, PATTERNS, clampLane, springStep, overlaps, playerBounds, obstacleBounds, trainBodyBounds, canLandOnRoof, coinCollected, wrapChunkZ, mulberry32, runnerAnimationState, jumpAnimationPhase, CHARACTERS, resolveCharacter, runCameraLayout, cycleCharacter, loadModelData, withTimeout } from "./logic.js";

const $ = selector => document.querySelector(selector);
const ui = {
  score: $("#score"), coins: $("#coins"), speed: $("#speed"),
  start: $("#startScreen"), pause: $("#pauseScreen"), over: $("#gameOverScreen"), error: $("#webglError"),
  finalScore: $("#finalScore"), finalCoins: $("#finalCoins"), best: $("#bestScore"), toast: $("#toast"), pauseButton: $("#pauseButton")
};

const C = { orange: 0xff7628, navy: 0x172641, cream: 0xf4f1df, red: 0xe64b3f, blue: 0x287db5, metal: 0x59616d, gold: 0xffc52f, mint: 0xb9cdc1 };
const mat = (color, roughness = .72, metalness = 0) => new THREE.MeshStandardMaterial({ color, roughness, metalness });
const materials = { orange:mat(C.orange), navy:mat(C.navy), cream:mat(C.cream), red:mat(C.red), blue:mat(C.blue), metal:mat(C.metal,.35,.65), dark:mat(0x202631), glass:mat(0x263951,.18,.25), gold:mat(C.gold,.25,.7), white:mat(0xffffff), skin:mat(0xf4b58d), brown:mat(0x593728), gravel:mat(0x6d736f), concrete:mat(0xbac4bb), green:mat(0x698e78) };
const box = (w,h,d,m) => new THREE.Mesh(new THREE.BoxGeometry(w,h,d),m);
const cyl = (r,h,m,segments=12) => { const mesh=new THREE.Mesh(new THREE.CylinderGeometry(r,r,h,segments),m); return mesh; };
function shadow(mesh) { mesh.castShadow=true; mesh.receiveShadow=true; return mesh; }
function add(parent, child, x=0,y=0,z=0) { child.position.set(x,y,z); parent.add(child); return child; }
function captureRigBind(rig) {
  rig.bind={};
  for(const [name,node] of Object.entries(rig)) if(node?.isObject3D) rig.bind[name]={position:node.position.clone(),rotation:node.rotation.clone()};
  return rig;
}

function createRunner() {
  const root=new THREE.Group(), rig={root};
  const shadowDisc=new THREE.Mesh(new THREE.CircleGeometry(.68,24),new THREE.MeshBasicMaterial({color:0x172641,transparent:true,opacity:.23,depthWrite:false}));
  shadowDisc.rotation.x=-Math.PI/2; add(root,shadowDisc,0,.012,0); rig.shadow=shadowDisc;
  const hips=add(root,new THREE.Group(),0,1.05,0); rig.hips=hips;
  const torso=shadow(box(.9,1.02,.52,materials.orange)); add(hips,torso,0,.55,0); torso.rotation.x=-.08;
  const chest=add(torso,box(.92,.23,.56,materials.navy),0,.26,0);
  const hood=new THREE.Mesh(new THREE.TorusGeometry(.36,.14,8,18,Math.PI),materials.orange); hood.rotation.set(Math.PI/2,0,Math.PI); add(hips,hood,0,1.05,.02);
  const backpack=shadow(box(.64,.78,.28,materials.navy)); add(hips,backpack,0,.57,.37);
  add(backpack,box(.42,.12,.3,materials.blue),0,.1,.03);
  const neck=add(hips,cyl(.15,.2,materials.skin),0,1.15,0); neck.rotation.z=Math.PI/2;
  const head=shadow(new THREE.Mesh(new THREE.SphereGeometry(.38,18,14),materials.skin)); add(hips,head,0,1.48,0);
  const hair=new THREE.Mesh(new THREE.SphereGeometry(.4,14,10,0,Math.PI*2,0,Math.PI*.52),materials.brown); add(hips,hair,0,1.61,-.02);
  const band=new THREE.Mesh(new THREE.TorusGeometry(.43,.075,8,24,Math.PI),materials.navy); band.rotation.z=Math.PI/2; add(hips,band,0,1.55,0);
  for(const side of [-1,1]) { const ear=cyl(.18,.12,side<0?materials.blue:materials.orange,16); ear.rotation.z=Math.PI/2; add(hips,ear,side*.42,1.51,0); }
  const leg=(side)=>{ const pivot=add(hips,new THREE.Group(),side*.25,0,0); add(pivot,shadow(box(.3,.85,.34,materials.navy)),0,-.43,0); const shoe=shadow(box(.43,.22,.72,materials.white)); add(pivot,shoe,0,-.9,-.18); add(shoe,box(.44,.12,.3,materials.orange),0,.08,-.17); return pivot; };
  rig.leftLeg=leg(-1); rig.rightLeg=leg(1);
  const arm=(side)=>{ const pivot=add(hips,new THREE.Group(),side*.57,.85,0); add(pivot,shadow(box(.25,.75,.27,materials.orange)),0,-.35,0); add(pivot,new THREE.Mesh(new THREE.SphereGeometry(.16,12,9),materials.skin),0,-.77,0); return pivot; };
  rig.leftArm=arm(-1); rig.rightArm=arm(1);
  root.scale.setScalar(.92); root.rotation.y=Math.PI;
  root.userData.rig=captureRigBind(rig);root.userData.characterId="classic"; return root;
}

function createTrain(length=18) {
  const g=new THREE.Group();
  const body=shadow(box(2.72,2.55,length,materials.cream)); add(g,body,0,1.34,0);
  const roof=shadow(box(2.58,.18,length+.1,materials.metal)); add(g,roof,0,2.68,0);
  add(g,box(2.76,.33,length+.03,materials.blue),0,.46,0);
  add(g,box(2.77,.17,length+.04,materials.red),0,1.52,0);
  const nose=shadow(box(2.73,2.24,.5,materials.cream)); add(g,nose,0,1.28,length/2+.24); nose.rotation.x=-.05;
  add(g,box(1.82,.7,.04,materials.glass),0,1.83,length/2+.51);
  for(const x of [-.78,.78]) { const light=new THREE.Mesh(new THREE.SphereGeometry(.13,12,8),materials.gold); add(g,light,x,.83,length/2+.52); }
  for(let z=-length/2+1.4;z<length/2-1;z+=2.15) for(const x of [-1.371,1.371]) add(g,box(.035,.68,1.25,materials.glass),x,1.85,z);
  for(const z of [-length*.3,length*.3]) for(const x of [-1.05,1.05]) { const wheel=cyl(.31,.16,materials.dark,16); wheel.rotation.z=Math.PI/2; add(g,wheel,x,.25,z); }
  return g;
}

function createBarrier(kind) {
  const g=new THREE.Group();
  const striped=(w,h,d)=>{ const beam=box(w,h,d,materials.red); for(let x=-w/2+.28;x<w/2;x+=.62){ const stripe=box(.25,h+.015,d+.02,materials.white); stripe.rotation.z=-.55; add(beam,stripe,x,0,0); } return beam; };
  if(kind==="low") {
    add(g,shadow(striped(2.45,.65,.3)),0,.62,0);
    for(const x of [-1.02,1.02]) add(g,shadow(box(.18,.75,.23,materials.dark)),x,.37,0);
  } else {
    for(const x of [-1.16,1.16]) add(g,shadow(box(.22,2.15,.25,materials.dark)),x,1.07,0);
    add(g,shadow(striped(2.65,.58,.32)),0,1.62,0);
  }
  return g;
}

function createCoin() {
  const g=new THREE.Group();
  const coin=new THREE.Mesh(new THREE.CylinderGeometry(.25,.25,.08,20),materials.gold); coin.rotation.z=Math.PI/2; g.add(coin);
  const ring=new THREE.Mesh(new THREE.TorusGeometry(.16,.035,6,16),materials.white); ring.rotation.y=Math.PI/2; g.add(ring); return g;
}

class Game {
  constructor() {
    this.phase="welcome"; this.distance=0; this.coinCount=0; this.speed=10; this.entities=[]; this.nextZ=-34; this.seed=1337; this.random=mulberry32(this.seed); this.toastTimer=0; this.shake=0; this.accumulator=0; this.runPhase=0; this.last=performance.now();
    this.player={lane:1,x:0,vx:0,y:0,vy:0,sliding:false,slideTime:0,support:null,dead:false}; this.slideHeld=false;
    let savedCharacter=null;try{savedCharacter=localStorage.getItem("railboundCharacter");}catch{}
    this.characterId=resolveCharacter(new URLSearchParams(location.search).get("model"),savedCharacter);
    this.characterModels=new Map();this.characterRequest=0;this.characterLoading=false;this.previewAngle="front";
    this.initScene(); this.bind(); this.syncCharacterUI();this.updateMenuPreview();requestAnimationFrame(t=>this.loop(t));
  }
  initScene(){
    const mount=$("#scene");
    try { this.renderer=new THREE.WebGLRenderer({antialias:true,powerPreference:"high-performance"}); } catch { ui.error.classList.add("visible"); throw new Error("WebGL unavailable"); }
    this.renderer.setPixelRatio(Math.min(devicePixelRatio,1.75)); this.renderer.setSize(innerWidth,innerHeight,false); this.renderer.outputColorSpace=THREE.SRGBColorSpace; this.renderer.toneMapping=THREE.ACESFilmicToneMapping; this.renderer.toneMappingExposure=1.12; this.renderer.shadowMap.enabled=true; this.renderer.shadowMap.type=THREE.PCFSoftShadowMap; mount.append(this.renderer.domElement);
    this.scene=new THREE.Scene(); this.scene.background=new THREE.Color(0xc7d7cd); this.scene.fog=new THREE.Fog(0xc7d7cd,48,165);
    this.camera=new THREE.PerspectiveCamera(58,innerWidth/innerHeight,.1,220); this.camera.position.set(0,5.4,10.2); this.camera.lookAt(0,1,-13);
    this.scene.add(new THREE.HemisphereLight(0xe6fff4,0x536275,2.1)); const sun=new THREE.DirectionalLight(0xfff0cf,3.2); sun.position.set(-10,18,8); sun.castShadow=true; sun.shadow.mapSize.set(1536,1536); sun.shadow.camera.left=-18;sun.shadow.camera.right=18;sun.shadow.camera.top=25;sun.shadow.camera.bottom=-8; this.scene.add(sun);
    this.world=new THREE.Group(); this.scene.add(this.world); this.makeEnvironment(); this.runner=createRunner(); this.runner.position.set(0,0,PLAYER_Z); this.scene.add(this.runner); this.loadRunnerModel(); this.loadAncientEnvironment();
  }
  loadRunnerModel(){this.selectCharacter(this.characterId);}
  async getCharacterModel(character,signal,onProgress){
    if(this.characterModels.has(character.id))return this.characterModels.get(character.id);
    const url=new URL(`${import.meta.env.BASE_URL}models/${character.file}`,document.baseURI);
    const data=await loadModelData(url.href,{signal,onProgress});
    signal.throwIfAborted();
    $("#characterStatus").textContent=`${character.name}下载完成，正在解析三维模型…`;
    const gltf=await withTimeout(new GLTFLoader().parseAsync(data,new URL(".",url).href),15000,"模型解析超时，请重试或切换其他跑者");
    signal.throwIfAborted();
      const model=new THREE.Group(),content=gltf.scene;model.name=`${character.id}_Gameplay`;
      content.rotation.y=Math.PI;content.scale.setScalar(character.scale);model.add(content);model.userData.content=content;model.userData.visualScale=character.scale;
      const nodes={};let hasSkin=false;
      content.traverse(node=>{nodes[node.name]=node;if(node.isSkinnedMesh)hasSkin=true;if(node.isMesh){node.castShadow=true;node.receiveShadow=true;}});
      const rig={root:model};
      if(character.animation==="clips"){
        const clips=new Map(gltf.animations.map(clip=>[clip.name,clip]));
        if(!hasSkin||!["Idle","Run","Jump","Slide"].every(name=>clips.has(name)))throw new Error("Character skin or gameplay clips are missing");
        const mixer=new THREE.AnimationMixer(content),actions={};
        for(const name of ["Idle","Run","Jump","Slide"]){
          const action=mixer.clipAction(clips.get(name));
          action.setLoop(name==="Jump"?THREE.LoopOnce:THREE.LoopRepeat,name==="Jump"?1:Infinity);
          action.clampWhenFinished=name==="Jump";actions[name]=action;
        }
        model.userData.animation={mixer,actions,current:null,jumpDuration:clips.get("Jump").duration};
      }else{
        const names={hips:"Hips_PIVOT",torso:"Torso_PIVOT",head:"Head_PIVOT",leftLeg:"Left_Hip_PIVOT",rightLeg:"Right_Hip_PIVOT",leftKnee:"Left_Knee_PIVOT",rightKnee:"Right_Knee_PIVOT",leftAnkle:"Left_Ankle_PIVOT",rightAnkle:"Right_Ankle_PIVOT",leftArm:"Left_Shoulder_PIVOT",rightArm:"Right_Shoulder_PIVOT",leftElbow:"Left_Elbow_PIVOT",rightElbow:"Right_Elbow_PIVOT",leftWrist:"Left_Wrist_PIVOT",rightWrist:"Right_Wrist_PIVOT"};
        for(const [key,name] of Object.entries(names))rig[key]=nodes[name]||null;
        if(!rig.hips||!rig.leftLeg||!rig.rightLeg)throw new Error("Original character pivots are missing");
        captureRigBind(rig);
      }
      model.userData.rig=rig;model.userData.characterId=character.id;
      this.characterModels.set(character.id,model);return model;
  }
  async selectCharacter(id){
    const character=CHARACTERS.find(item=>item.id===id);if(!character||!["welcome","menu"].includes(this.phase))return;
    this.characterController?.abort();
    this.characterController=new AbortController();
    $("#retryCharacter").hidden=true;
    const request=++this.characterRequest;this.characterId=id;this.characterLoading=true;
    this.syncCharacterUI(`正在加载${character.name}…`);
    try{
      let lastProgress=0;
      const model=await this.getCharacterModel(character,this.characterController.signal,loaded=>{
        if(request!==this.characterRequest||performance.now()-lastProgress<200)return;
        lastProgress=performance.now();
        $("#characterStatus").textContent=`正在下载${character.name} · ${(loaded/1024/1024).toFixed(1)} MB`;
      });
      if(request!==this.characterRequest)return;
      const previous=this.runner,shadowDisc=previous.userData.rig.shadow;
      if(model!==previous){
        previous.userData.animation?.mixer.stopAllAction();
        model.position.copy(previous.position);model.rotation.set(0,0,previous.rotation.z);
        shadowDisc.removeFromParent();model.add(shadowDisc);model.userData.rig.shadow=shadowDisc;
        this.scene.remove(previous);this.runner=model;this.scene.add(model);
      }
      const animation=model.userData.animation;
      if(animation){animation.mixer.stopAllAction();animation.current=null;this.animateImportedRunner(0);}
      else this.animatePlayer(0,true);
      model.updateMatrixWorld(true);
      const previewBounds=new THREE.Box3().setFromObject(model,true),previewSize=previewBounds.getSize(new THREE.Vector3());
      model.userData.previewFrame={size:previewSize,center:previewBounds.getCenter(new THREE.Vector3()).sub(model.position)};
      this.characterLoading=false;
      try{localStorage.setItem("railboundCharacter",id);}catch{}
      const url=new URL(location.href);url.searchParams.set("model",id);history.replaceState(null,"",url);
      this.syncCharacterUI("左右切换跑者，选好后开始奔跑");
      this.updateMenuPreview();
    }catch(error){
      if(request!==this.characterRequest)return;
      console.warn(`Character ${id} failed to load`,error);this.characterLoading=false;
      this.characterId=this.runner.userData.characterId||id;
      this.failedCharacterId=id;$("#retryCharacter").hidden=false;
      this.syncCharacterUI(`${character.name}加载失败：${error.message||"网络异常"}。可重试、切换或使用当前跑者开始。`);
    }
  }
  syncCharacterUI(message){
    const character=CHARACTERS.find(item=>item.id===this.characterId);
    $("#characterName").textContent=character.name;
    const selecting=this.phase==="menu";
    $("#characterIndex").textContent=`${String(CHARACTERS.indexOf(character)+1).padStart(2,"0")} / ${String(CHARACTERS.length).padStart(2,"0")}`;
    $("#runnerPreview").setAttribute("aria-label",`${character.name}的三维预览`);
    ui.start.classList.toggle("visible",this.phase==="welcome");
    $("#characterScreen").classList.toggle("visible",selecting);
    $("#characterPanel").hidden=!selecting;
    $("#characterPanel").dataset.mode=this.phase;
    $("#runnerPreview").hidden=!selecting||!!this.previewUnavailable;
    $("#selectionActions").hidden=!selecting;
    document.querySelector(".hud").hidden=this.phase==="welcome"||selecting;
    this.runner.visible=this.phase!=="welcome";
    $("#characterPanel").setAttribute("aria-busy",String(this.characterLoading));
    for(const id of ["#startButton","#restartButton","#resumeButton"])$(id).disabled=this.characterLoading;
    if(message)$("#characterStatus").textContent=message;
    this.runner.rotation.y=selecting&&this.previewAngle==="front"?Math.PI:0;
  }
  switchCharacter(direction){
    if(this.phase!=="menu")return;
    this.selectCharacter(cycleCharacter(this.characterId,direction));
  }
  enterGame(){
    if(!["welcome","over"].includes(this.phase))return;
    document.activeElement?.blur();
    this.clearEntities();this.slideHeld=false;this.accumulator=0;this.runPhase=0;this.shake=0;
    Object.assign(this.player,{lane:1,x:0,vx:0,y:0,vy:0,sliding:false,slideTime:0,support:"ground",dead:false});
    this.runner.position.set(0,0,PLAYER_Z);this.runner.rotation.set(0,0,0);
    const animation=this.runner.userData.animation;
    if(animation){animation.mixer.stopAllAction();animation.current=null;}
    this.phase="menu";this.animatePlayer(0,true);
    ui.over.classList.remove("visible");ui.pause.classList.remove("visible");
    this.camera.position.set(0,5.4,10.2);this.camera.fov=58;this.camera.lookAt(0,1,-13);this.camera.updateProjectionMatrix();
    this.syncCharacterUI();this.updateMenuPreview();
    $("#startButton").focus();
  }
  returnToWelcome(){
    if(this.phase!=="menu")return;
    this.phase="welcome";this.syncCharacterUI();
    this.camera.position.set(0,5.4,10.2);this.camera.fov=58;this.camera.lookAt(0,1,-13);this.camera.updateProjectionMatrix();
    $("#enterButton").focus();
  }
  updateMenuPreview(){
    if(this.phase!=="menu")return;
    this.runner.rotation.y=this.previewAngle==="front"?Math.PI:0;
  }
  renderRunnerPreview(){
    if(this.phase!=="menu"||this.previewUnavailable)return;
    const canvas=$("#runnerPreview"),width=canvas.clientWidth,height=canvas.clientHeight;
    if(!width||!height)return;
    try{
      if(!this.previewRenderer){
        this.previewRenderer=new THREE.WebGLRenderer({canvas,alpha:true,antialias:true});
        this.previewRenderer.setPixelRatio(Math.min(devicePixelRatio,1.5));
        this.previewRenderer.outputColorSpace=THREE.SRGBColorSpace;
        this.previewRenderer.toneMapping=THREE.ACESFilmicToneMapping;this.previewRenderer.toneMappingExposure=1.12;
        this.previewCamera=new THREE.PerspectiveCamera(32,width/height,.1,30);
      }
      if(this.previewWidth!==width||this.previewHeight!==height){
        this.previewRenderer.setSize(width,height,false);this.previewWidth=width;this.previewHeight=height;
        this.previewCamera.aspect=width/height;this.previewCamera.updateProjectionMatrix();
      }
      const frame=this.runner.userData.previewFrame||{size:new THREE.Vector3(2,2.6,1),center:new THREE.Vector3(0,1.3,0)};
      const halfFov=Math.tan(THREE.MathUtils.degToRad(16));
      const previewDistance=1.2*Math.max(frame.size.y/(2*halfFov),frame.size.x/(2*this.previewCamera.aspect*halfFov))+frame.size.z/2;
      const previewTarget=this.runner.position.clone().add(frame.center);
      this.previewCamera.position.set(previewTarget.x,previewTarget.y+.35,previewTarget.z+previewDistance);
      this.previewCamera.lookAt(previewTarget);
      const background=this.scene.background,fog=this.scene.fog,worldVisible=this.world.visible;
      try{
        this.world.visible=false;this.scene.background=null;this.scene.fog=null;
        this.previewRenderer.render(this.scene,this.previewCamera);
      }finally{this.world.visible=worldVisible;this.scene.background=background;this.scene.fog=fog;}
    }catch(error){
      console.warn("Runner preview unavailable; game remains playable",error);
      this.previewUnavailable=true;canvas.hidden=true;this.previewRenderer?.dispose();this.previewRenderer=null;
    }
  }
  animateImportedRunner(dt){
    const p=this.player,animation=this.runner.userData.animation;
    if(this.phase==="paused"&&animation.current!==null)return;
    const name=runnerAnimationState(p,this.phase==="paused"?"running":this.phase);
    if(animation.current!==name){
      const previous=animation.actions[animation.current],next=animation.actions[name];
      // Enter the low pose immediately: collider height changes on the same step.
      const duration=name==="Slide"||animation.current===null?0:.1;
      if(duration===0){for(const action of Object.values(animation.actions))action.stop();}
      else if(previous)previous.fadeOut(duration);
      next.reset().setEffectiveWeight(1).setEffectiveTimeScale(1).play();
      if(duration>0)next.fadeIn(duration);animation.current=name;
    }
    animation.actions.Run.setEffectiveTimeScale(this.speed/10);
    const jumpAction=animation.actions.Jump;
    if(name==="Jump"){
      let landingY=GROUND_Y;
      for(const entity of this.entities){
        if(entity.kind!=="train"||p.y<entity.roofY)continue;
        const body=trainBodyBounds(entity);
        if(p.x+.38>=body.minX&&p.x-.38<=body.maxX&&PLAYER_Z+.34>=body.minZ&&PLAYER_Z-.34<=body.maxZ)landingY=Math.max(landingY,entity.roofY);
      }
      jumpAction.setEffectiveTimeScale(0);jumpAction.time=jumpAnimationPhase(p,landingY)*animation.jumpDuration;
    }
    animation.mixer.update(this.phase==="paused"?0:dt);
    // Enlarge the visual only; keep the original slide height below the high rail.
    this.runner.userData.content.scale.y=name==="Slide"?1:this.runner.userData.visualScale;
    for(const [key,action] of Object.entries(animation.actions)){
      if(key!==name&&action.getEffectiveWeight()<=.0001)action.stop();
    }
    this.runner.position.set(p.x,p.y,PLAYER_Z);
    this.runner.rotation.z=THREE.MathUtils.lerp(this.runner.rotation.z,-p.vx*.035,Math.min(1,dt*10));
    const shadowDisc=this.runner.userData.rig.shadow,scale=Math.max(.15,1-p.y*.12);
    shadowDisc.position.y=-p.y+.012;shadowDisc.scale.setScalar(scale);shadowDisc.material.opacity=.23*scale;
  }
  makeEnvironment(){
    const floor=box(14,.2,210,materials.concrete); add(this.world,floor,0,-.18,-78); floor.receiveShadow=true;
    for(const laneX of LANES) for(const side of [-.58,.58]) { const rail=box(.1,.12,210,materials.metal); add(this.world,rail,laneX+side,.03,-78); rail.receiveShadow=true; }
    this.sceneryChunks=[];this.chunkLength=54;this.chunkCount=4;
    for(let index=0;index<this.chunkCount;index++){
      const chunk=new THREE.Group();chunk.position.z=-index*this.chunkLength;chunk.userData.decorations=new THREE.Group();chunk.add(chunk.userData.decorations);
      for(const laneX of LANES)for(let z=-this.chunkLength/2;z<this.chunkLength/2;z+=1.2)add(chunk,box(1.72,.09,.24,materials.brown),laneX,-.06,z);
      for(const side of [-1,1]){
        add(chunk,box(.55,1.2,this.chunkLength,materials.concrete),side*8.2,.42,0);
        for(let z=-18;z<=18;z+=12){const h=3.2+((index+Math.abs(z))%3)*.65;const house=box(3.8,h,6.2,materials.cream);add(chunk.userData.decorations,house,side*10.4,h/2,z);const roof=box(4.35,.35,6.75,materials.green);add(chunk.userData.decorations,roof,side*10.4,h+.08,z);}
      }
      this.world.add(chunk);this.sceneryChunks.push(chunk);
    }
    this.makeDistantEnvironment();
  }
  makeDistantEnvironment(){
    this.backgroundChunks=[];this.backgroundChunkLength=96;this.backgroundChunkCount=3;
    for(let index=0;index<this.backgroundChunkCount;index++){
      const chunk=new THREE.Group();chunk.position.z=-index*this.backgroundChunkLength;chunk.userData.decorations=new THREE.Group();chunk.add(chunk.userData.decorations);
      for(const side of [-1,1]){
        add(chunk.userData.decorations,box(6,3.8,this.backgroundChunkLength,materials.cream),side*18,1.7,0);
        for(let z=-44;z<=44;z+=22){const tower=box(5.5,7,5.5,materials.cream);add(chunk.userData.decorations,tower,side*(16+Math.abs(z%3)),3.5,z);const roof=box(7,.45,7,materials.green);roof.rotation.y=Math.PI/4;add(chunk.userData.decorations,roof,tower.position.x,7.05,z);}
      }
      this.world.add(chunk);this.backgroundChunks.push(chunk);
    }
  }
  loadAncientEnvironment(){
    new GLTFLoader().load(`${import.meta.env.BASE_URL}models/environment/ancient_railway.glb`,gltf=>{
      for(const [index,chunk] of this.sceneryChunks.entries()){chunk.userData.decorations.clear();const model=gltf.scene.clone(true);model.traverse(o=>{if(o.isMesh){o.receiveShadow=true;o.castShadow=o.name.includes("House")||o.name.includes("Paifang");}});model.rotation.y=index%2?Math.PI:0;chunk.userData.decorations.add(model);}
    },undefined,error=>console.warn("Ancient railway GLB failed; using procedural fallback",error));
    this.loadDistantEnvironment();
  }
  loadDistantEnvironment(){
    new GLTFLoader().load(`${import.meta.env.BASE_URL}models/environment/ancient_skyline.glb`,gltf=>{
      for(const [index,chunk] of this.backgroundChunks.entries()){chunk.userData.decorations.clear();const model=gltf.scene.clone(true);model.rotation.y=index%2?Math.PI:0;model.traverse(o=>{if(o.isMesh){o.castShadow=false;o.receiveShadow=false;}});chunk.userData.decorations.add(model);}
    },undefined,error=>console.warn("Ancient skyline GLB failed; using procedural fallback",error));
  }
  bind(){
    addEventListener("resize",()=>this.resize()); addEventListener("keydown",e=>this.key(e,true),{passive:false}); addEventListener("keyup",e=>this.key(e,false),{passive:false});
    $("#enterButton").onclick=()=>this.enterGame();$("#backButton").onclick=()=>this.returnToWelcome();
    $("#startButton").onclick=()=>this.start(); $("#restartButton").onclick=()=>this.enterGame(); $("#resumeButton").onclick=()=>this.togglePause(); ui.pauseButton.onclick=()=>this.togglePause();
    $("#previousCharacter").onclick=()=>this.switchCharacter(-1);$("#nextCharacter").onclick=()=>this.switchCharacter(1);
    $("#retryCharacter").onclick=()=>this.selectCharacter(this.failedCharacterId);
    document.querySelectorAll("[data-preview-angle]").forEach(button=>button.onclick=()=>{
      if(this.phase!=="menu")return;
      this.previewAngle=button.dataset.previewAngle;
      document.querySelectorAll("[data-preview-angle]").forEach(item=>item.setAttribute("aria-pressed",String(item===button)));
      if(this.phase==="menu")this.updateMenuPreview();
      else this.runner.rotation.y=this.previewAngle==="front"?Math.PI:0;
    });
    document.addEventListener("visibilitychange",()=>{if(document.hidden&&this.phase==="running")this.togglePause();});
  }
  key(e,down){
    if(!down&&(e.key==="ArrowDown"||e.key.toLowerCase()==="s"))this.slideHeld=false;
    if(e.target?.closest?.("input,select,textarea"))return;
    if(["Enter"," "].includes(e.key)&&e.target?.closest?.("button,a")&&e.target.getClientRects().length)return;
    const handled=["ArrowLeft","ArrowRight","ArrowUp","ArrowDown"," ","a","d","w","s","p","Escape","Enter"].includes(e.key)||["a","d","w","s","p"].includes(e.key.toLowerCase()); if(handled)e.preventDefault();
    if(!down){if(e.key==="ArrowDown"||e.key.toLowerCase()==="s")this.slideHeld=false;return;} if(e.repeat&&e.key!=="ArrowDown")return;
    if(e.key==="Enter"&&this.phase==="welcome")return this.enterGame();
    if(e.key==="Escape"&&this.phase==="menu")return this.returnToWelcome();
    if(this.phase==="menu"&&(e.key==="ArrowLeft"||e.key==="ArrowRight"))return this.switchCharacter(e.key==="ArrowLeft"?-1:1);
    if(e.key==="Enter"&&this.phase==="over")return this.enterGame();
    if(e.key==="Enter"&&this.phase==="menu")return this.start(); if(e.key.toLowerCase()==="p"||e.key==="Escape")return this.togglePause(); if(this.phase!=="running")return;
    if(e.key==="ArrowLeft"||e.key.toLowerCase()==="a")this.player.lane=clampLane(this.player.lane-1);
    if(e.key==="ArrowRight"||e.key.toLowerCase()==="d")this.player.lane=clampLane(this.player.lane+1);
    if((e.key==="ArrowUp"||e.key.toLowerCase()==="w"||e.key===" ")&&this.player.support)this.jump();
    if((e.key==="ArrowDown"||e.key.toLowerCase()==="s")&&this.player.support){this.slideHeld=true;this.player.sliding=true;this.player.slideTime=.35;}
  }
  jump(){this.player.vy=11.2;this.player.support=null;this.player.sliding=false;}
  start(){if(this.characterLoading||this.phase!=="menu")return;document.activeElement?.blur();this.slideHeld=false;this.runner.rotation.y=0;this.accumulator=0;this.runPhase=0;const animation=this.runner.userData.animation;if(animation){animation.mixer.stopAllAction();animation.current=null;}this.clearEntities();this.distance=0;this.coinCount=0;this.speed=10;this.nextZ=-28;this.random=mulberry32(this.seed++);Object.assign(this.player,{lane:1,x:0,vx:0,y:0,vy:0,sliding:false,slideTime:0,support:"ground",dead:false});this.phase="running";ui.start.classList.remove("visible");ui.over.classList.remove("visible");ui.pause.classList.remove("visible");ui.pauseButton.textContent="Ⅱ";this.last=performance.now();this.resetRunCamera();this.spawnUntilFull();this.updateHud();this.syncCharacterUI();}
  togglePause(){document.activeElement?.blur();if(this.phase==="running"){this.phase="paused";this.slideHeld=false;ui.pause.classList.add("visible");ui.pauseButton.textContent="▶";}else if(this.phase==="paused"&&!this.characterLoading){this.phase="running";this.runner.rotation.y=0;ui.pause.classList.remove("visible");ui.pauseButton.textContent="Ⅱ";this.last=performance.now();}this.syncCharacterUI();}
  end(){if(this.phase!=="running")return;this.phase="over";this.player.dead=true;this.shake=.38;const score=Math.floor(this.distance);const best=Math.max(score,Number(localStorage.getItem("neonTideBest")||0));localStorage.setItem("neonTideBest",String(best));ui.finalScore.textContent=score.toLocaleString("zh-CN");ui.finalCoins.textContent=this.coinCount;ui.best.textContent=best.toLocaleString("zh-CN");this.syncCharacterUI();setTimeout(()=>{if(this.phase==="over"){ui.over.classList.add("visible");this.syncCharacterUI();}},850);}
  clearEntities(){for(const e of this.entities)this.world.remove(e.mesh);this.entities=[];}
  spawnUntilFull(){while(this.nextZ>-145)this.spawnPattern();}
  spawnPattern(){const difficulty=Math.min(4,Math.floor(this.distance/500));const available=PATTERNS.slice(0,Math.min(PATTERNS.length,2+difficulty));const pattern=available[Math.floor(this.random()*available.length)];for(const p of pattern.placements){const z=this.nextZ-p.at;if(p.kind==="coinLine"||p.kind==="coinArc"){for(let i=0;i<p.count;i++){let y=.95;if(p.kind==="coinArc")y=.95+Math.sin((i/(p.count-1))*Math.PI)*2.7;this.spawnEntity("coin",p.lane,z-i*1.35,{y});}}else this.spawnEntity(p.kind,p.lane,z,{length:p.length||0});}this.nextZ-=pattern.length;}
  spawnEntity(kind,lane,z,extra={}){let mesh,entity={kind,lane,z,baseY:0,...extra};if(kind==="train"){entity.length=extra.length;entity.roofY=2.78;mesh=createTrain(entity.length);}else if(kind==="coin")mesh=createCoin();else mesh=createBarrier(kind);entity.mesh=mesh;mesh.position.set(LANES[lane],kind==="coin"?entity.y:0,z);this.world.add(mesh);this.entities.push(entity);}
  update(dt){
    if(this.phase!=="running")return;
    this.speed=Math.min(18,10+this.distance/700);const dz=this.speed*dt;this.distance+=dz;this.nextZ+=dz;
    for(const chunk of this.sceneryChunks)chunk.position.z=wrapChunkZ(chunk.position.z,dz,this.chunkLength,this.chunkCount,this.chunkLength/2);
    for(const chunk of this.backgroundChunks)chunk.position.z=wrapChunkZ(chunk.position.z,dz*.55,this.backgroundChunkLength,this.backgroundChunkCount,this.backgroundChunkLength/2);
    const s=springStep(this.player.x,this.player.vx,LANES[this.player.lane],dt,11);this.player.x=s.position;this.player.vx=s.velocity;
    const previousY=this.player.y;this.player.slideTime=Math.max(0,this.player.slideTime-dt);if(this.player.slideTime<=0&&!this.slideHeld)this.player.sliding=false;
    if(!this.player.support){this.player.vy-=19.5*dt;this.player.y+=this.player.vy*dt;}
    for(const e of this.entities){e.z+=dz;e.mesh.position.z=e.z;if(e.kind==="coin"){e.mesh.rotation.y+=dt*6;e.mesh.position.y=e.y+Math.sin(performance.now()*.004+e.z)*.08;}}
    this.resolveSupport(previousY); this.resolveCollisions();
    if(this.phase!=="running"){this.updateHud();return;}
    if(!this.player.support&&this.player.y<=GROUND_Y){this.player.y=GROUND_Y;this.player.vy=0;this.player.support="ground";this.land();}
    if(this.player.support==="ground")this.player.y=GROUND_Y;
    this.entities=this.entities.filter(e=>{if(e.z<24)return true;this.world.remove(e.mesh);return false;});this.spawnUntilFull();this.animatePlayer(dt);this.updateCamera(dt);this.updateHud();if(this.toastTimer>0){this.toastTimer-=dt;if(this.toastTimer<=0)ui.toast.classList.remove("show");}
  }
  resolveSupport(previousY){
    const trains=this.entities.filter(e=>e.kind==="train");let supporting=null;
    for(const train of trains)if(canLandOnRoof(this.player,previousY,train)){supporting=train;break;}
    if(supporting){const was=this.player.support;this.player.y=supporting.roofY;this.player.vy=0;this.player.support=supporting;if(was!==supporting){this.land();this.toast("落上车顶！");}return;}
    if(this.player.support&&this.player.support!=="ground"){
      const b=trainBodyBounds(this.player.support);const still=this.player.x+.34>=b.minX&&this.player.x-.34<=b.maxX&&PLAYER_Z>=b.minZ&&PLAYER_Z<=b.maxZ;
      if(!still)this.player.support=null;else this.player.y=this.player.support.roofY;
    }
  }
  resolveCollisions(){
    const pb=playerBounds(this.player);
    for(const e of this.entities){
      if(e.collected)continue;
      if(e.kind==="coin"){if(coinCollected(this.player,e)){e.collected=true;e.mesh.visible=false;this.coinCount++;this.distance+=12;this.toast(this.coinCount%10===0?`${this.coinCount} 枚金币！`:"金币 +1");}continue;}
      if(e.kind==="low"||e.kind==="high"){if(overlaps(pb,obstacleBounds(e)))return this.end();continue;}
      if(e.kind==="train"){
        const body=trainBodyBounds(e);const onRoof=this.player.support===e&&Math.abs(this.player.y-e.roofY)<.05;
        if(!onRoof&&overlaps(pb,body))return this.end();
      }
    }
  }
  land(){this.shake=Math.max(this.shake,.1);this.runner.userData.land=.18;}
  animatePlayer(dt,initialize=false){
    if(this.phase==="over"&&!initialize)return;
    if(this.phase==="paused"&&!this.runner.userData.animation&&!initialize)return;
    if(this.runner.userData.animation){this.animateImportedRunner(dt);return;}
    const p=this.player,rig=this.runner.userData.rig;if(!rig)return;
    const active=(this.phase==="running"||(initialize&&this.phase==="paused"))&&!p.dead,slide=active&&p.sliding?1:0,air=active&&!p.support?1:0,blend=initialize?1:Math.min(1,dt*14);
    if(active)this.runPhase+=dt*(8.8+this.speed*.22);
    const phase=this.runPhase,step=Math.sin(phase),opposite=-step,leftRecovery=Math.max(0,Math.sin(phase)),rightRecovery=Math.max(0,Math.sin(phase+Math.PI));
    const bind=rig.bind||{},angle=(name,axis,offset)=>{const node=rig[name],base=bind[name];if(node&&base)node.rotation[axis]=THREE.MathUtils.lerp(node.rotation[axis],base.rotation[axis]+offset,blend);};
    const move=(name,axis,offset)=>{const node=rig[name],base=bind[name];if(node&&base)node.position[axis]=THREE.MathUtils.lerp(node.position[axis],base.position[axis]+offset,blend);};
    this.runner.position.set(p.x,p.y,PLAYER_Z);this.runner.rotation.z=THREE.MathUtils.lerp(this.runner.rotation.z,-p.vx*.035,Math.min(1,dt*10));
    const running=active&&!slide&&!air,idleBob=!active?Math.sin(performance.now()*.0025)*.008:0;
    move("hips","y",idleBob+(running?Math.abs(Math.sin(phase*2))*.075:0)-slide*.46);
    angle("hips","x",slide*.92+air*.1);angle("hips","z",running?step*.045:0);angle("torso","x",active?.13:0);angle("torso","y",running?-step*.07:0);angle("head","x",active?-.045:0);angle("head","y",running?step*.035:0);
    angle("leftLeg","x",slide?1.18:(air?-.45:step*.78));angle("rightLeg","x",slide?-.52:(air?.62:opposite*.78));
    angle("leftKnee","x",slide?-1.5:(air?-1.05:-leftRecovery*1.18-.08));angle("rightKnee","x",slide?-1.12:(air?-.5:-rightRecovery*1.18-.08));
    angle("leftAnkle","x",slide?.28:(air?.22:leftRecovery*.42-step*.16));angle("rightAnkle","x",slide?.35:(air?-.12:rightRecovery*.42-opposite*.16));
    angle("leftArm","x",slide?-.68:(air?-.28:-step*.68));angle("rightArm","x",slide?.58:(air?.42:step*.68));
    angle("leftElbow","x",slide?-1.25:-.82-leftRecovery*.22);angle("rightElbow","x",slide?-1.05:-.82-rightRecovery*.22);
    angle("leftWrist","x",running?step*.08:0);angle("rightWrist","x",running?opposite*.08:0);
    rig.shadow.position.y=-p.y+.012;const ss=Math.max(.15,1-p.y*.12);rig.shadow.scale.setScalar(ss);rig.shadow.material.opacity=.23*ss;
  }
  resetRunCamera(){
    this.camera.fov=58;
    const layout=runCameraLayout(this.camera.aspect,this.camera.fov);
    this.camera.position.set(this.player.x*.24,layout.height,layout.z);
    this.camera.lookAt(this.camera.position.x*.25,layout.targetY,layout.targetZ);
    this.camera.updateProjectionMatrix();
  }
  updateCamera(dt){
    const reduced=matchMedia("(prefers-reduced-motion: reduce)").matches,targetX=this.player.x*.24;
    this.camera.position.x=THREE.MathUtils.lerp(this.camera.position.x,targetX,dt*3.5);
    const targetFov=58+(this.speed-10)*.45;
    this.camera.fov=THREE.MathUtils.lerp(this.camera.fov,targetFov,dt*2);
    const layout=runCameraLayout(this.camera.aspect,this.camera.fov);
    this.shake=Math.max(0,this.shake-dt);
    const bump=reduced?0:(Math.random()-.5)*this.shake;
    this.camera.position.y=layout.height+bump;this.camera.position.z=layout.z+bump*.35;
    this.camera.lookAt(this.camera.position.x*.25,layout.targetY,layout.targetZ);
    this.camera.updateProjectionMatrix();
  }
  updateHud(){ui.score.textContent=String(Math.floor(this.distance)).padStart(5,"0");ui.coins.textContent=this.coinCount;ui.speed.textContent=`${(this.speed/10).toFixed(1)}×`;}
  toast(text){ui.toast.textContent=text;ui.toast.classList.add("show");this.toastTimer=.72;}
  resize(){this.camera.aspect=innerWidth/innerHeight;this.camera.updateProjectionMatrix();this.renderer.setPixelRatio(Math.min(devicePixelRatio,1.75));this.renderer.setSize(innerWidth,innerHeight,false);if(["running","paused","over"].includes(this.phase))this.resetRunCamera();this.updateMenuPreview();}
  loop(now){const frame=Math.min(.05,(now-this.last)/1000||0);this.last=now;if(this.phase==="running"){this.accumulator+=frame;let steps=0;while(this.phase==="running"&&this.accumulator>=1/60&&steps++<4){this.update(1/60);this.accumulator-=1/60;}if(this.phase!=="running")this.accumulator=0;}else this.animatePlayer(Math.min(frame,.02));this.renderer.render(this.scene,this.camera);this.renderRunnerPreview();requestAnimationFrame(t=>this.loop(t));}
}

try { const game=new Game();if(import.meta.env.DEV)window.__railboundGame=game; } catch (error) { console.error(error); ui.error.classList.add("visible"); }
