// Attribute-aware mesh processing: do not weld across material/UV boundaries.
import { NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS } from "@gltf-transform/extensions";
import { dedup, prune, simplify, weld } from "@gltf-transform/functions";
import { MeshoptSimplifier } from "meshoptimizer";

const [source, output, count] = process.argv.slice(2);
const target = Number(count);
if (
  !source ||
  !output ||
  !Number.isInteger(target) ||
  target < 1000 ||
  target > 300000
)
  throw new Error("Invalid target triangle count");
await MeshoptSimplifier.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS);
const document = await io.read(source);
const triangles = document
  .getRoot()
  .listMeshes()
  .reduce(
    (sum, mesh) =>
      sum +
      mesh
        .listPrimitives()
        .reduce(
          (n, p) =>
            n +
            (p.getIndices()?.getCount() ??
              p.getAttribute("POSITION").getCount()) /
              3,
          0,
        ),
    0,
  );
if (triangles > target) {
  await document.transform(
    weld(),
    simplify({
      simplifier: MeshoptSimplifier,
      ratio: target / triangles,
      error: 0.01,
      lockBorder: true,
    }),
    dedup(),
    prune(),
  );
}
await io.write(output, document);
