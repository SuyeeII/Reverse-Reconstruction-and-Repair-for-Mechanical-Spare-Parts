# 机械备件项目的第三方组件

本项目实现多视图量测、参数设计、结构校核、制造导出及 AGH 领域插件。[项目许可](LICENSE)。

图像与几何计算使用 OpenCV、COLMAP/pycolmap、Open3D、CadQuery 和 trimesh；网格与有限元使用 Gmsh 和 scikit-fem；制造路径由单独安装的 PrusaSlicer 生成。具体 Python 版本见依赖文件。

AGH 和 SDK 从仓库外安装接入。浏览器、字体和其他随包资源保留各自目录内的原始许可；`licenses/` 保存相关第三方条款。
