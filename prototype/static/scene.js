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
  let selected = null;
  let signature = "";

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
    const length = THREE.MathUtils.clamp(offset.length(), 4, 40);
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
    const wallH = 0.95;
    const t = 0.08;
    mesh(width, 0.08, depth, 0, -0.04, 0, 0xe7e1d6);
    mesh(width, wallH, t, 0, wallH / 2, -depth / 2, 0xe7e2da);
    mesh(t, wallH, depth, -width / 2, wallH / 2, 0, 0xe7e2da);
    mesh(t, wallH, depth, width / 2, wallH / 2, 0, 0xe4e0d8);
    const gap = width * 0.38;
    const side = (width - gap) / 2;
    mesh(side, wallH, t, -(gap + side) / 2, wallH / 2, depth / 2, 0xe7e2da);
    mesh(side, wallH, t, (gap + side) / 2, wallH / 2, depth / 2, 0xe7e2da);
    mesh(gap, wallH * 0.72, 0.02, 0, wallH * 0.55, depth / 2 - 0.02, 0xd5e4ec);

    for (const x of [-width * 0.28, width * 0.08]) {
      mesh(width * 0.34, 0.08, 0.7, x, 0.42, 0.15, 0xddd6cb);
    }

    const pole = mesh(0.08, 1.3, 0.08, -width * 0.12, 0.65, -depth * 0.08, 0x8d877c);
    pole.castShadow = true;
    mesh(0.46, 0.24, 0.28, -width * 0.12, 1.36, -depth * 0.08, CALM, "sensor");

    mesh(1.1, 0.42, 0.1, 0, 0.72, depth / 2 - 0.14, IDLE, "air_in");
    mesh(1.1, 0.42, 0.1, 0, 0.72, -depth / 2 + 0.14, IDLE, "air_out");
    arrows.air_in = new THREE.ArrowHelper(new THREE.Vector3(0, 0, -1), new THREE.Vector3(0, 0.7, depth / 2 - 0.55), 0.9, ACTIVE, 0.22, 0.14);
    arrows.air_out = new THREE.ArrowHelper(new THREE.Vector3(0, 0, -1), new THREE.Vector3(0, 0.7, -depth / 2 + 0.35), 0.9, ACTIVE, 0.22, 0.14);
    arrows.air_in.visible = false;
    arrows.air_out.visible = false;
    root.add(arrows.air_in, arrows.air_out);

    const span = Math.max(width, depth, ceiling);
    camera.position.set(span * 0.95, span * 0.82, span * 1.05);
    controls.target.set(0, 0.5, 0);
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
    const sensor = materials.sensor;
    if (sensor) {
      const alert = quality === "ok" && co2 >= 1000;
      const waiting = quality && quality !== "ok";
      sensor.color.setHex(waiting ? IDLE : alert ? WARM : CALM);
    }
    const mode = record?.air_mode;
    if (materials.air_in) materials.air_in.color.setHex(mode === "air_in" ? ACTIVE : IDLE);
    if (materials.air_out) materials.air_out.color.setHex(mode === "air_out" ? ACTIVE : IDLE);
    if (arrows.air_in) arrows.air_in.visible = mode === "air_in";
    if (arrows.air_out) arrows.air_out.visible = mode === "air_out";
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
