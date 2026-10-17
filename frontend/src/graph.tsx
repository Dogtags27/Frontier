import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

export type GraphNode = { id: string; label: string; kind: "read" | "gap" | "path" };

const COLOR = { read: "#5fb3a6", gap: "#e0912f", path: "#d9e6e3", core: "#ffffff" };

export function StudentGraph({ nodes, name }: { nodes: GraphNode[]; name: string }) {
  const host = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState("");

  useEffect(() => {
    const node = host.current;
    if (!node) return;
    const width = node.clientWidth || 640;
    const height = node.clientHeight || 416;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#0c1f24");
    scene.fog = new THREE.Fog("#0c1f24", 9, 18);
    const camera = new THREE.PerspectiveCamera(42, width / height, 0.1, 100);
    camera.position.set(0, 3.2, 8.5);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width, height);
    node.replaceChildren(renderer.domElement);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enablePan = false;
    controls.enableDamping = true;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.7;
    controls.minDistance = 4;
    controls.maxDistance = 13;

    const seen = new Set<string>();
    const rank = { gap: 0, path: 1, read: 2 } as const;
    const unique = [...nodes]
      .sort((a, b) => rank[a.kind] - rank[b.kind])
      .filter((item) => (seen.has(item.id) ? false : (seen.add(item.id), true)))
      .slice(0, 36);

    const core = new THREE.Mesh(new THREE.SphereGeometry(0.28, 28, 28), new THREE.MeshBasicMaterial({ color: COLOR.core }));
    scene.add(core);
    const halo = new THREE.Mesh(new THREE.SphereGeometry(0.46, 28, 28), new THREE.MeshBasicMaterial({ color: "#e0912f", transparent: true, opacity: 0.18 }));
    scene.add(halo);

    const ring = (r: number, opacity: number) => {
      const points = Array.from({ length: 65 }, (_, i) => new THREE.Vector3(Math.cos((i / 64) * Math.PI * 2) * r, 0, Math.sin((i / 64) * Math.PI * 2) * r));
      scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), new THREE.LineBasicMaterial({ color: "#2f5a63", transparent: true, opacity })));
    };
    ring(1.5, 0.55);
    ring(2.7, 0.4);
    ring(3.7, 0.3);

    const groups = { gap: unique.filter((n) => n.kind === "gap"), path: unique.filter((n) => n.kind === "path"), read: unique.filter((n) => n.kind === "read") };
    const radius = { gap: 1.5, path: 2.7, read: 3.7 };
    const meshes: THREE.Mesh[] = [];
    const placed = new Map<string, THREE.Vector3>();

    (Object.keys(groups) as (keyof typeof groups)[]).forEach((kind) => {
      const list = groups[kind];
      list.forEach((item, index) => {
        const angle = (index / Math.max(list.length, 1)) * Math.PI * 2 + (kind === "path" ? 0.4 : kind === "read" ? 0.9 : 0);
        const y = kind === "path" ? 0.55 : kind === "gap" ? 0 : -0.45 + (index % 3) * 0.3;
        const mesh = new THREE.Mesh(
          new THREE.SphereGeometry(kind === "gap" ? 0.2 : 0.13, 20, 20),
          new THREE.MeshBasicMaterial({ color: COLOR[kind] }),
        );
        mesh.position.set(Math.cos(angle) * radius[kind], y, Math.sin(angle) * radius[kind]);
        mesh.userData = { label: item.label, kind };
        scene.add(mesh);
        meshes.push(mesh);
        placed.set(item.id, mesh.position);
        const edge = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0, 0), mesh.position]);
        scene.add(
          new THREE.Line(
            edge,
            new THREE.LineBasicMaterial({ color: kind === "gap" ? "#e0912f" : "#2f5a63", transparent: true, opacity: kind === "gap" ? 0.55 : 0.28 }),
          ),
        );
      });
    });
    for (let index = 1; index < groups.path.length; index += 1) {
      const a = placed.get(groups.path[index - 1].id);
      const b = placed.get(groups.path[index].id);
      if (a && b) scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([a, b]), new THREE.LineBasicMaterial({ color: "#d9e6e3", transparent: true, opacity: 0.6 })));
    }

    let frame = 0;
    let pulse = 0;
    const tick = () => {
      frame = requestAnimationFrame(tick);
      pulse += 0.03;
      halo.scale.setScalar(1 + Math.sin(pulse) * 0.12);
      controls.update();
      renderer.render(scene, camera);
    };
    tick();

    const ray = new THREE.Raycaster();
    const onMove = (event: PointerEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      const mouse = new THREE.Vector2(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
      ray.setFromCamera(mouse, camera);
      const hit = ray.intersectObjects(meshes)[0];
      setTip(hit ? `${String(hit.object.userData.kind)}: ${String(hit.object.userData.label || "")}` : "");
      renderer.domElement.style.cursor = hit ? "pointer" : "";
    };
    const stop = () => (controls.autoRotate = false);
    renderer.domElement.addEventListener("pointermove", onMove);
    renderer.domElement.addEventListener("pointerdown", stop);

    const observer = new ResizeObserver(() => {
      const w = node.clientWidth;
      const h = node.clientHeight;
      if (!w || !h) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    });
    observer.observe(node);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      renderer.domElement.removeEventListener("pointermove", onMove);
      renderer.domElement.removeEventListener("pointerdown", stop);
      controls.dispose();
      scene.traverse((object) => {
        if (object instanceof THREE.Mesh || object instanceof THREE.Line) {
          object.geometry.dispose();
          const material = object.material;
          if (Array.isArray(material)) material.forEach((item) => item.dispose());
          else material.dispose();
        }
      });
      renderer.dispose();
    };
  }, [nodes]);

  return (
    <div className="graph-shell">
      <div className="graph3d" ref={host} aria-label={`Research graph for ${name}`} />
      <div className="graph-legend">
        <span>
          <i style={{ background: COLOR.core }} />
          {name}
        </span>
        <span>
          <i style={{ background: COLOR.gap }} />
          Gaps
        </span>
        <span>
          <i style={{ background: COLOR.path }} />
          Reading path
        </span>
        <span>
          <i style={{ background: COLOR.read }} />
          Papers read
        </span>
      </div>
      {tip && <div className="graph-tip">{tip}</div>}
    </div>
  );
}
