// Görsel sekmesi: 3D model önizleme (media_panel.ModelView). Fareyle döndür, tekerlekle yakınlaştır.
// Model sahnenin ortasına alınır ve ekrana sığacak kadar ölçeklenir; gerçek ölçüleri `dims` ile bildirilir.
import QtQuick
import QtQuick3D
import QtQuick3D.Helpers
import QtQuick3D.AssetUtils

Rectangle {
    id: root
    color: "#1b1b1f"
    property url source
    property string status: loader.status === RuntimeLoader.Success ? "ok"
                          : (loader.status === RuntimeLoader.Error ? "hata: " + loader.errorString : "")
    property string dims: ""

    function reset() {
        cam.position = Qt.vector3d(0, 0, 330)
        cam.eulerRotation = Qt.vector3d(0, 0, 0)
        origin.eulerRotation = Qt.vector3d(-20, 30, 0)
    }

    View3D {
        anchors.fill: parent
        environment: SceneEnvironment {
            clearColor: root.color
            backgroundMode: SceneEnvironment.Color
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
        }
        Node {
            id: origin
            eulerRotation: Qt.vector3d(-20, 30, 0)
            PerspectiveCamera { id: cam; position: Qt.vector3d(0, 0, 330); clipNear: 1; clipFar: 10000 }
        }
        DirectionalLight { eulerRotation.x: -35; eulerRotation.y: -40; brightness: 1.4 }
        DirectionalLight { eulerRotation.x: 25; eulerRotation.y: 150; brightness: 0.6 }
        RuntimeLoader {
            id: loader
            source: root.source
            onBoundsChanged: {
                var mn = bounds.minimum, mx = bounds.maximum
                var sx = mx.x - mn.x, sy = mx.y - mn.y, sz = mx.z - mn.z
                var size = Math.max(sx, sy, sz)
                if (size <= 0) return
                root.dims = sx.toFixed(1) + " × " + sy.toFixed(1) + " × " + sz.toFixed(1)
                var s = 200 / size
                scale = Qt.vector3d(s, s, s)
                position = Qt.vector3d(-(mn.x + mx.x) / 2 * s, -(mn.y + mx.y) / 2 * s, -(mn.z + mx.z) / 2 * s)
            }
        }
    }
    OrbitCameraController { anchors.fill: parent; origin: origin; camera: cam }
}
