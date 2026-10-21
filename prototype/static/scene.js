import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const CALM = 0x2f7d57;
const WARM = 0xc4512c;
const IDLE = 0xc8c2b8;
const ACTIVE = 0xd97848;

export function createClassroom(canvas, onSelect) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xf3f1ec);

  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 200);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.maxPolarAngle = Math.PI / 2.15;
  controls.minPolarAngle = 0.55;
  controls.target.set(0, 0.6, 0);

  scene.add(new THREE.AmbientLight(0xffffff, 0.85));
  const sun = new THREE.DirectionalLight(0xfff6ea, 1.15);
  sun.position.set(8, 14, 6);
  sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024);
  scene.add(sun);

  const root = new THREE.Group();
  scene.add(root);
  const pickables = [];
  const materials = {};
  let arrows = { air_in: null, air_out: null };
  let fanGroup = null;
  let flowDots = [];
  let flowAnchor = null;
  let flowLength = 1;
  let selected = null;
  let signature = "";
  let roomSpan = 12;

  function resize() {
    const width = canvas.clientWidth || 640;
    const height = canvas.clientHeight || 480;
    if (canvas.width !== Math.floor(width * renderer.getPixelRatio())) {
      renderer.setSize(width, height, false);
    }
    camera.aspect = width / Math.max(height, 1);
    camera.updateProjectionMatrix();
  }

  function zoom(direction) {
    const offset = new THREE.Vector3().subVectors(camera.position, controls.target);
    offset.multiplyScalar(direction > 0 ? 0.82 : 1.22);
    const length = THREE.MathUtils.clamp(offset.length(), roomSpan * 0.45, roomSpan * 3.2);
    offset.setLength(length);
    camera.position.copy(controls.target).add(offset);
  }

  function clearRoot() {
    for (const child of [...root.children]) {
      root.remove(child);
      child.traverse((obj) => {
        obj.geometry?.dispose();
        if (Array.isArray(obj.material)) obj.material.forEach((item) => item.dispose());
        else obj.material?.dispose();
      });
    }
    pickables.length = 0;
    arrows = { air_in: null, air_out: null };
    fanGroup = null;
    flowDots = [];
    flowAnchor = null;
  }

  function mesh(w, h, d, x, y, z, color, id) {
    const material = new THREE.MeshStandardMaterial({ color, roughness: 0.86 });
    const box = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
    box.position.set(x, y, z);
    box.castShadow = true;
    box.receiveShadow = true;
    if (id) {
      box.userData.id = id;
      pickables.push(box);
      materials[id] = material;
    }
    root.add(box);
    return box;
  }

  function build(area, ceiling) {
    clearRoot();
    const ratio = 1.25;
    const width = Math.sqrt(area / ratio);
    const depth = width * ratio;
    const wallH = Math.max(ceiling, 2.6);
    const t = 0.12;
    roomSpan = Math.max(width, depth, wallH);

    mesh(width, 0.08, depth, 0, -0.04, 0, 0xd9cbb8);
    mesh(width, wallH, t, 0, wallH / 2, -depth / 2, 0xf4f0e8);
    mesh(t, wallH, depth, -width / 2, wallH / 2, 0, 0xefeae2);
    mesh(width * 0.22, 0.9, t, -width * 0.28, 0.45, depth / 2, 0xf7f3ec);
    mesh(width * 0.22, 0.9, t, width * 0.28, 0.45, depth / 2, 0xf7f3ec);
    mesh(width * 0.34, wallH * 0.55, 0.04, 0, wallH * 0.62, depth / 2 - 0.02, 0xc5d8e4);

    mesh(width * 0.42, wallH * 0.28, 0.04, 0, wallH * 0.62, -depth / 2 + t, 0xf7f7f5);
    mesh(0.7, 0.04, 1.3, 0, 0.78, -depth / 2 + 0.85, 0xc8b89a);

    const rows = 3;
    const cols = 3;
    for (let row = 0; row < rows; row += 1) {
      for (let col = 0; col < cols; col += 1) {
        const x = (col - 1) * width * 0.24;
        const z = (row - 0.2) * depth * 0.18;
        mesh(width * 0.16, 0.05, depth * 0.08, x, 0.74, z, 0xe4d3b8);
        mesh(0.28, 0.45, 0.28, x, 0.28, z + depth * 0.055, 0xb7c3c9);
      }
    }

    const sensorX = -width / 2 + 0.16;
    const sensorY = 1.5;
    const sensorZ = depth * 0.05;
    mesh(0.06, 0.16, 0.22, sensorX, sensorY, sensorZ, CALM, "sensor");
    const ledMaterial = new THREE.MeshStandardMaterial({ color: CALM, emissive: CALM, emissiveIntensity: 0.8 });
    const led = new THREE.Mesh(new THREE.SphereGeometry(0.045, 16, 12), ledMaterial);
    led.position.set(sensorX + 0.04, sensorY + 0.05, sensorZ);
    led.userData.id = "sensor";
    pickables.push(led);
    materials.led = ledMaterial;
    root.add(led);

    const fanX = width * 0.3;
    const fanY = wallH * 0.68;
    const fanZ = depth / 2 - 0.22;
    const shroudMat = new THREE.MeshStandardMaterial({ color: IDLE, roughness: 0.72 });
    const shroud = new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.7, 0.08), shroudMat);
    shroud.position.set(fanX, fanY, fanZ + 0.08);
    shroud.userData.id = "fan";
    pickables.push(shroud);
    materials.fan = shroudMat;
    materials.air_in = shroudMat;
    materials.air_out = shroudMat;
    root.add(shroud);

    fanGroup = new THREE.Group();
    fanGroup.position.set(fanX, fanY, fanZ);
    fanGroup.rotation.x = Math.PI / 2;
    const hubMaterial = new THREE.MeshStandardMaterial({ color: 0x4d4944, roughness: 0.45 });
    const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.07, 0.05, 16), hubMaterial);
    hub.userData.id = "fan";
    pickables.push(hub);
    fanGroup.add(hub);
    const bladeReach = 0.28;
    for (let blade = 0; blade < 4; blade += 1) {
      const vane = new THREE.Mesh(
        new THREE.BoxGeometry(bladeReach, 0.02, 0.08),
        new THREE.MeshStandardMaterial({ color: 0xe4ddd4, roughness: 0.65 }),
      );
      vane.position.x = bladeReach * 0.55;
      vane.userData.id = "fan";
      pickables.push(vane);
      const arm = new THREE.Group();
      arm.rotation.y = blade * (Math.PI / 2);
      arm.add(vane);
      fanGroup.add(arm);
    }
    root.add(fanGroup);

    flowAnchor = { x: fanX, y: fanY, z: fanZ };
    flowLength = Math.min(depth * 0.42, 3.2);
    const flowMat = new THREE.MeshBasicMaterial({ color: 0x8ec3db, transparent: true, opacity: 0.75 });
    flowDots = [];
    for (let i = 0; i < 9; i += 1) {
      const dot = new THREE.Mesh(new THREE.SphereGeometry(0.055, 10, 8), flowMat);
      dot.userData.offset = i / 9;
      dot.visible = false;
      root.add(dot);
      flowDots.push(dot);
    }

    camera.position.set(roomSpan * 0.72, wallH * 1.15, roomSpan * 0.95);
    controls.target.set(0, wallH * 0.38, 0);
    controls.update();
    applySelection();
  }

  function applySelection() {
    for (const [id, material] of Object.entries(materials)) {
      material.emissive = new THREE.Color(selected === id ? 0x3a3328 : 0x000000);
      material.emissiveIntensity = selected === id ? 0.28 : 0;
    }
  }

  function paint(record) {
    const co2 = record?.co2_ppm;
    const quality = record?.quality?.co2;
    const alert = quality === "ok" && co2 >= 1000;
    const waiting = Boolean(quality && quality !== "ok");
    const mode = record?.air_mode;
    if (materials.sensor) materials.sensor.color.setHex(waiting ? IDLE : alert ? WARM : CALM);
    if (materials.led) {
      materials.led.color.setHex(waiting ? IDLE : alert ? WARM : CALM);
      materials.led.emissive.setHex(waiting ? IDLE : alert ? WARM : CALM);
      materials.led.emissiveIntensity = 0.85;
    }
    const spinning = mode === "air_in" || mode === "air_out";
    const direction = mode === "air_in" ? 1 : mode === "air_out" ? -1 : 0;
    if (fanGroup) fanGroup.userData.direction = direction;
    if (materials.fan) materials.fan.color.setHex(spinning ? ACTIVE : IDLE);
    flowDots.forEach((dot) => {
      dot.visible = spinning;
    });
  }

  function update(state) {
    const spec = state?.twin?.spec;
    if (!spec) return;
    const next = `${spec.floor_area_m2}:${spec.ceiling_m}`;
    if (next !== signature) {
      signature = next;
      build(spec.floor_area_m2, spec.ceiling_m);
    }
    paint(state.record);
  }

  function choose(id) {
    selected = id;
    applySelection();
    onSelect(id);
  }

  canvas.addEventListener("pointerdown", (event) => {
    const rect = canvas.getBoundingClientRect();
    const ray = new THREE.Raycaster();
    ray.setFromCamera(new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    ), camera);
    const hits = ray.intersectObjects(pickables, false);
    if (!hits.length) {
      selected = null;
      applySelection();
      onSelect(null);
      return;
    }
    choose(hits[0].object.userData.id);
  });

  function frame() {
    resize();
    const direction = fanGroup?.userData.direction || 0;
    if (fanGroup && direction) fanGroup.rotation.y += direction * 0.28;
    if (flowAnchor && direction) {
      flowDots.forEach((dot) => {
        dot.userData.offset = (dot.userData.offset + 0.006) % 1;
        const travel = direction > 0 ? dot.userData.offset : 1 - dot.userData.offset;
        dot.position.set(
          flowAnchor.x + Math.sin(dot.userData.offset * Math.PI * 2) * 0.12,
          flowAnchor.y + Math.cos(dot.userData.offset * Math.PI * 2) * 0.08,
          flowAnchor.z - travel * flowLength,
        );
      });
    }
    controls.update();
    renderer.render(scene, camera);
    requestAnimationFrame(frame);
  }
  frame();

  return {
    update,
    zoom,
    select(id) {
      choose(id);
    },
  };
}
