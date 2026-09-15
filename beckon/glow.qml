// Soft orange edge glow shown while Beckon is reading the screen.
// Click-through, on every screen, pulses until the process is killed.
import Quickshell
import Quickshell.Wayland
import QtQuick

ShellRoot {
  // Safety: never linger if the parent that started us dies.
  Timer { interval: 60000; running: true; onTriggered: Qt.quit() }

  Variants {
    model: Quickshell.screens
    PanelWindow {
      required property var modelData
      screen: modelData
      anchors { top: true; bottom: true; left: true; right: true }
      color: "transparent"
      exclusiveZone: 0
      WlrLayershell.layer: WlrLayer.Overlay
      WlrLayershell.namespace: "beckon-glow"
      mask: Region {}          // let every click pass straight through

      Item {
        id: glow
        anchors.fill: parent
        property int thick: 110
        property color c: "#ff8a1f"

        SequentialAnimation on opacity {
          loops: Animation.Infinite
          NumberAnimation { from: 0.35; to: 1.0; duration: 700; easing.type: Easing.InOutSine }
          NumberAnimation { from: 1.0; to: 0.35; duration: 700; easing.type: Easing.InOutSine }
        }

        Rectangle { anchors { top: parent.top; left: parent.left; right: parent.right }
          height: glow.thick
          gradient: Gradient { orientation: Gradient.Vertical
            GradientStop { position: 0.0; color: Qt.rgba(glow.c.r, glow.c.g, glow.c.b, 0.55) }
            GradientStop { position: 1.0; color: "transparent" } } }
        Rectangle { anchors { bottom: parent.bottom; left: parent.left; right: parent.right }
          height: glow.thick
          gradient: Gradient { orientation: Gradient.Vertical
            GradientStop { position: 0.0; color: "transparent" }
            GradientStop { position: 1.0; color: Qt.rgba(glow.c.r, glow.c.g, glow.c.b, 0.55) } } }
        Rectangle { anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
          width: glow.thick
          gradient: Gradient { orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: Qt.rgba(glow.c.r, glow.c.g, glow.c.b, 0.55) }
            GradientStop { position: 1.0; color: "transparent" } } }
        Rectangle { anchors { right: parent.right; top: parent.top; bottom: parent.bottom }
          width: glow.thick
          gradient: Gradient { orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "transparent" }
            GradientStop { position: 1.0; color: Qt.rgba(glow.c.r, glow.c.g, glow.c.b, 0.55) } } }
      }
    }
  }
}
