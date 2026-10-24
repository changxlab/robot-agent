// Point-cloud viewer for .pcd / .ply files (three.js, vendored under /static/vendor/three).
// Loaded lazily by index.html: `const { mountPointCloud } = await import("/static/pointcloud-viewer.js")`.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { PCDLoader } from "three/addons/loaders/PCDLoader.js";
import { PLYLoader } from "three/addons/loaders/PLYLoader.js";

// Turbo-like colormap stops for colouring by height / intensity.
const RAMP = [[0.19, 0.07, 0.23], [0.16, 0.47, 0.93], [0.1, 0.84, 0.66], [0.64, 0.99, 0.24],
  [0.98, 0.73, 0.22], [0.89, 0.27, 0.05], [0.48, 0.02, 0.01]];

function ramp(t, out, i) {
  const x = Math.min(Math.max(t, 0), 1) * (RAMP.length - 1);
  const k = Math.min(Math.floor(x), RAMP.length - 2), f = x - k, a = RAMP[k], b = RAMP[k + 1];
  out[i] = a[0] + (b[0] - a[0]) * f; out[i + 1] = a[1] + (b[1] - a[1]) * f; out[i + 2] = a[2] + (b[2] - a[2]) * f;
}

// Colours from a scalar, using the 2nd-98th percentile so outliers don't flatten the ramp.
function scalarColors(values, stride, offset) {
  const n = values.length / stride, sample = [];
  const step = Math.max(1, Math.floor(n / 20000));
  for (let i = 0; i < n; i += step) sample.push(values[i * stride + offset]);
  sample.sort((a, b) => a - b);
  const lo = sample[Math.floor(sample.length * 0.02)] ?? 0, hi = sample[Math.floor(sample.length * 0.98)] ?? 1;
  const span = hi - lo || 1, colors = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) ramp((values[i * stride + offset] - lo) / span, colors, i * 3);
  return colors;
}

function load(url, ext, onProgress) {
  const loader = ext === "ply" ? new PLYLoader() : new PCDLoader();
  return new Promise((resolve, reject) => {
    loader.load(url, (res) => resolve(res.isPoints ? res.geometry : res), (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    }, (err) => reject(err instanceof Error ? err : new Error(`HTTP ${err?.target?.status ?? "error"}`)));
  });
}

/**
 * Render a point cloud into `container`.
 * opts: { url, ext: "pcd"|"ply", onProgress(fraction), onInfo({points, size, colorModes, mode}) }
 * Returns a handle: { resetView(), setPointSize(px), setColorMode(name), toggleGrid(show), dispose() }.
 */
export async function mountPointCloud(container, opts) {
  const { url, ext = "pcd", onProgress = () => {}, onInfo = () => {} } = opts;
  let disposed = false, frame = 0;

  const geometry = await load(url, ext, onProgress);

  const pos = geometry.getAttribute("position");
  if (!pos || !pos.count) throw new Error("The file contains no points.");
  geometry.computeBoundingBox(); geometry.computeBoundingSphere();
  const box = geometry.boundingBox, sphere = geometry.boundingSphere;
  const size = box.getSize(new THREE.Vector3());

  const colorModes = {};
  if (geometry.getAttribute("color")) colorModes.rgb = geometry.getAttribute("color");
  colorModes.height = new THREE.BufferAttribute(scalarColors(pos.array, 3, 2), 3);
  const intensity = geometry.getAttribute("intensity");
  if (intensity) colorModes.intensity = new THREE.BufferAttribute(scalarColors(intensity.array, intensity.itemSize, 0), 3);
  let mode = colorModes.rgb ? "rgb" : "height";
  geometry.setAttribute("color", colorModes[mode]);

  const material = new THREE.PointsMaterial({ size: 2, sizeAttenuation: false, vertexColors: true });
  const points = new THREE.Points(geometry, material);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x15161a);
  scene.add(points);
  const gridSize = Math.max(size.x, size.y, 1);
  const grid = new THREE.GridHelper(gridSize * 1.2, 20, 0x555555, 0x2c2c2c);
  grid.rotation.x = Math.PI / 2; // robot data is Z-up
  grid.position.set(sphere.center.x, sphere.center.y, box.min.z);
  scene.add(grid);
  const axes = new THREE.AxesHelper(Math.max(gridSize * 0.08, 0.3));
  scene.add(axes);

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  container.appendChild(renderer.domElement);

  const radius = Math.max(sphere.radius, 0.1);
  const camera = new THREE.PerspectiveCamera(55, 1, radius / 1000, radius * 50);
  camera.up.set(0, 0, 1);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.screenSpacePanning = true;

  function resetView() {
    controls.target.copy(sphere.center);
    camera.position.copy(sphere.center).add(new THREE.Vector3(-1.1, -1.4, 0.9).multiplyScalar(radius));
    controls.update();
  }
  resetView();

  function resize() {
    const w = container.clientWidth || 1, h = container.clientHeight || 1;
    renderer.setSize(w, h, false);
    camera.aspect = w / h; camera.updateProjectionMatrix();
  }
  const observer = new ResizeObserver(resize);
  observer.observe(container); resize();

  (function animate() {
    if (disposed) return;
    frame = requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  })();

  onInfo({ points: pos.count, size: [size.x, size.y, size.z], colorModes: Object.keys(colorModes), mode });

  return {
    resetView,
    setPointSize(px) { material.size = px; },
    setColorMode(name) {
      if (!colorModes[name]) return;
      mode = name;
      geometry.setAttribute("color", colorModes[name]);
    },
    toggleGrid(show) { grid.visible = axes.visible = show; },
    dispose() {
      disposed = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      controls.dispose();
      geometry.dispose(); material.dispose(); grid.geometry.dispose(); axes.geometry.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
    },
  };
}
