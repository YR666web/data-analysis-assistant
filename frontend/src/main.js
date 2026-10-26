import { createApp } from 'vue'
import {
  ElButton, ElCheckbox, ElDropdown, ElDropdownItem, ElDropdownMenu, ElEmpty,
  ElIcon, ElInput, ElProgress, ElScrollbar, ElSwitch, ElTabPane, ElTabs,
  ElTag, ElTooltip, ElUpload,
} from 'element-plus'
import {
  ArrowDown, CaretRight, CircleCheck, CircleCheckFilled, CircleClose, Close,
  Collection, CopyDocument, DataLine, Delete, Document, Download, Expand,
  Fold, FolderOpened, InfoFilled, Link, MagicStick, Moon, Position,
  RefreshRight, Search, Sunny, UploadFilled, VideoPause, Warning,
  WarningFilled, ZoomIn, ZoomOut,
} from '@element-plus/icons-vue'
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/checkbox/style/css'
import 'element-plus/es/components/dropdown/style/css'
import 'element-plus/es/components/dropdown-item/style/css'
import 'element-plus/es/components/dropdown-menu/style/css'
import 'element-plus/es/components/empty/style/css'
import 'element-plus/es/components/icon/style/css'
import 'element-plus/es/components/input/style/css'
import 'element-plus/es/components/progress/style/css'
import 'element-plus/es/components/scrollbar/style/css'
import 'element-plus/es/components/switch/style/css'
import 'element-plus/es/components/tab-pane/style/css'
import 'element-plus/es/components/tabs/style/css'
import 'element-plus/es/components/tag/style/css'
import 'element-plus/es/components/tooltip/style/css'
import 'element-plus/es/components/upload/style/css'
import App from './App.vue'
import './style.css'
import { applyTheme } from './store'

const app = createApp(App)
// Explicit registration also keeps string-based dynamic icons available to Vue.
const components = {
  ElButton, ElCheckbox, ElDropdown, ElDropdownItem, ElDropdownMenu, ElEmpty,
  ElIcon, ElInput, ElProgress, ElScrollbar, ElSwitch, ElTabPane, ElTabs,
  ElTag, ElTooltip, ElUpload,
  ArrowDown, CaretRight, CircleCheck, CircleCheckFilled, CircleClose, Close,
  Collection, CopyDocument, DataLine, Delete, Document, Download, Expand,
  Fold, FolderOpened, InfoFilled, Link, MagicStick, Moon, Position,
  RefreshRight, Search, Sunny, UploadFilled, VideoPause, Warning,
  WarningFilled, ZoomIn, ZoomOut,
}
for (const [key, component] of Object.entries(components)) {
  app.component(key, component)
}
applyTheme()
app.mount('#app')
