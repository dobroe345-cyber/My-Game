// My-Game: 3D-платформер на C++ -> WebAssembly (WebGL2).
// Работает в Safari на iPhone/iPad. Управление: левый палец - ходьба, правый - камера,
// кнопка справа внизу - прыжок. На компьютере: WASD, пробел, стрелки.
//
// Оптимизации: один instanced draw-call на весь мир, frustum culling на CPU,
// фиксированный шаг физики, динамическое разрешение (подстраивается под FPS),
// без аллокаций в кадре, шейдеры без текстур (процедурные материалы).

#include <emscripten.h>
#include <emscripten/html5.h>
#include <GLES3/gl3.h>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <vector>
#include <algorithm>

EM_JS(int, js_width, (), { return window.innerWidth; });
EM_JS(int, js_height, (), { return window.innerHeight; });
EM_JS(double, js_dpr, (), { return window.devicePixelRatio || 1.0; });

namespace {

// ------------------------------------------------------------ math
struct Vec3 { float x, y, z; };
struct Mat4 { float m[16]; };

Vec3 normalize(Vec3 v) {
  float l = sqrtf(v.x * v.x + v.y * v.y + v.z * v.z);
  if (l < 1e-8f) return {0, 1, 0};
  return {v.x / l, v.y / l, v.z / l};
}
Vec3 cross(Vec3 a, Vec3 b) {
  return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x};
}
float dot(Vec3 a, Vec3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }

Mat4 mul(const Mat4& a, const Mat4& b) {
  Mat4 r;
  for (int c = 0; c < 4; c++)
    for (int row = 0; row < 4; row++) {
      float s = 0;
      for (int k = 0; k < 4; k++) s += a.m[k * 4 + row] * b.m[c * 4 + k];
      r.m[c * 4 + row] = s;
    }
  return r;
}

Mat4 perspective(float th /*tan(fovy/2)*/, float asp, float n, float f) {
  Mat4 r;
  memset(r.m, 0, sizeof(r.m));
  r.m[0] = 1.0f / (th * asp);
  r.m[5] = 1.0f / th;
  r.m[10] = (f + n) / (n - f);
  r.m[11] = -1.0f;
  r.m[14] = 2.0f * f * n / (n - f);
  return r;
}

Mat4 lookDir(Vec3 e, Vec3 f, Vec3 up, Vec3* outRight, Vec3* outUp) {
  Vec3 s = normalize(cross(f, up));
  Vec3 u = cross(s, f);
  Mat4 r;
  memset(r.m, 0, sizeof(r.m));
  r.m[0] = s.x;  r.m[4] = s.y;  r.m[8] = s.z;
  r.m[1] = u.x;  r.m[5] = u.y;  r.m[9] = u.z;
  r.m[2] = -f.x; r.m[6] = -f.y; r.m[10] = -f.z;
  r.m[12] = -dot(s, e);
  r.m[13] = -dot(u, e);
  r.m[14] = dot(f, e);
  r.m[15] = 1.0f;
  *outRight = s;
  *outUp = u;
  return r;
}

// ------------------------------------------------------------ world
struct Box {
  float c[3];    // центр
  float h[3];    // половинные размеры
  float col[3];  // цвет
  float rad;     // радиус описанной сферы (для culling)
};

std::vector<Box> g_boxes;
unsigned g_seed = 1337u;
float rnd() {
  g_seed = g_seed * 1664525u + 1013904223u;
  return (float)((g_seed >> 8) & 0xFFFFFF) / 16777216.0f;
}

void addBox(float cx, float cy, float cz, float hx, float hy, float hz, const float* col) {
  Box b;
  b.c[0] = cx; b.c[1] = cy; b.c[2] = cz;
  b.h[0] = hx; b.h[1] = hy; b.h[2] = hz;
  b.col[0] = col[0]; b.col[1] = col[1]; b.col[2] = col[2];
  b.rad = sqrtf(hx * hx + hy * hy + hz * hz);
  g_boxes.push_back(b);
}

const float PALETTE[6][3] = {
    {0.62f, 0.60f, 0.56f},  // бетон
    {0.55f, 0.42f, 0.32f},  // кирпич
    {0.40f, 0.46f, 0.52f},  // сталь
    {0.70f, 0.66f, 0.55f},  // песчаник
    {0.35f, 0.50f, 0.38f},  // мох
    {0.58f, 0.36f, 0.30f},  // ржавчина
};

void buildWorld() {
  g_boxes.clear();
  g_boxes.reserve(400);
  const float floorCol[3] = {0.45f, 0.47f, 0.44f};
  addBox(0, -1, 0, 90, 1, 90, floorCol);

  // лестница
  for (int i = 0; i < 16; i++) {
    float h = 0.4f * (i + 1);
    addBox(10.0f + i * 1.5f, h * 0.5f, 0, 0.75f, h * 0.5f, 3.0f, PALETTE[3]);
  }
  // площадка наверху лестницы
  addBox(10.0f + 16 * 1.5f + 3.0f, 3.2f, 0, 3.0f, 3.2f, 3.0f, PALETTE[2]);

  // спираль парящих платформ
  for (int i = 0; i < 22; i++) {
    float a = i * 0.55f;
    float r = 18.0f + i * 0.9f;
    addBox(cosf(a) * r, 2.0f + i * 0.95f, sinf(a) * r, 2.2f, 0.3f, 2.2f, PALETTE[(i % 3) + 1]);
  }
  // колонны
  for (int i = 0; i < 45; i++) {
    float a = rnd() * 6.2831853f;
    float r = 15.0f + rnd() * 60.0f;
    float h = 2.0f + rnd() * 8.0f;
    float w = 0.5f + rnd() * 0.7f;
    addBox(cosf(a) * r, h, sinf(a) * r, w, h, w, PALETTE[(int)(rnd() * 5.99f)]);
  }
  // низкие блоки
  for (int i = 0; i < 90; i++) {
    float a = rnd() * 6.2831853f;
    float r = 8.0f + rnd() * 70.0f;
    float hy = 0.3f + rnd() * 0.9f;
    float hx = 0.7f + rnd() * 1.6f;
    float hz = 0.7f + rnd() * 1.6f;
    float x = cosf(a) * r, z = sinf(a) * r;
    if (x > 6 && x < 40 && fabsf(z) < 6) continue;  // не перекрывать лестницу
    addBox(x, hy, z, hx, hy, hz, PALETTE[(int)(rnd() * 5.99f)]);
  }
}

// ------------------------------------------------------------ состояние
float g_pos[3] = {0, 2.0f, 0};
float g_vel[3] = {0, 0, 0};
float g_yaw = 0, g_pitch = -0.1f;
bool g_ground = false;
float g_coyote = 0;
const float HS[3] = {0.3f, 0.9f, 0.3f};
const float EYE = 0.7f;
const float SPEED = 6.5f, JUMP = 8.8f, GRAV = 22.0f;
const float STEP = 1.0f / 120.0f;

// ввод
bool kW, kA, kS, kD, kSpace, kL, kR, kU, kDn;
int moveId = -1, lookId = -1, jumpId = -1;
float stickOX, stickOY, stickX, stickY, lastLX, lastLY;
float cssW = 800, cssH = 600;

// рендер
EMSCRIPTEN_WEBGL_CONTEXT_HANDLE g_ctx;
GLuint progScene, progSky, progHud, vaoMesh, vaoEmpty, vboMesh, vboInst;
GLint uVP, uCam, uSun, uFogS;
GLint uSkyF, uSkyR, uSkyU, uSkyTan, uSkySun;
GLint uHudRect, uHudRes, uHudCol, uHudRing;
std::vector<float> g_inst;
Vec3 g_sun;
float g_scale = 1.0f;
int g_pw = 0, g_ph = 0;
double g_last = 0, g_acc = 0, g_avg = 1.0 / 60.0, g_lastScaleChange = 0;
int g_frame = 0;
bool g_needResize = true;

// ------------------------------------------------------------ шейдеры
const char* VS_SCENE = R"(#version 300 es
layout(location=0) in vec3 aPos;
layout(location=1) in vec3 aNorm;
layout(location=2) in vec3 iCenter;
layout(location=3) in vec3 iHalf;
layout(location=4) in vec3 iColor;
uniform mat4 uVP;
out vec3 vWorld;
out vec3 vN;
out vec3 vColor;
out vec3 vLocal;
flat out vec3 vHalf;
void main() {
  vec3 l = aPos * iHalf;
  vec3 w = iCenter + l;
  vWorld = w; vN = aNorm; vColor = iColor; vLocal = l; vHalf = iHalf;
  gl_Position = uVP * vec4(w, 1.0);
}
)";

const char* FS_SCENE = R"(#version 300 es
precision highp float;
in vec3 vWorld;
in vec3 vN;
in vec3 vColor;
in vec3 vLocal;
flat in vec3 vHalf;
uniform vec3 uCam;
uniform vec3 uSun;
uniform float uFogS;
out vec4 o;

float hash(vec3 p) {
  p = fract(p * 0.3183099 + 0.1);
  p *= 17.0;
  return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}
float noise(vec3 x) {
  vec3 i = floor(x), f = fract(x);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(hash(i), hash(i + vec3(1,0,0)), f.x),
                 mix(hash(i + vec3(0,1,0)), hash(i + vec3(1,1,0)), f.x), f.y),
             mix(mix(hash(i + vec3(0,0,1)), hash(i + vec3(1,0,1)), f.x),
                 mix(hash(i + vec3(0,1,1)), hash(i + vec3(1,1,1)), f.x), f.y), f.z);
}
float fbm(vec3 p) {
  float a = 0.5, s = 0.0;
  for (int i = 0; i < 3; i++) { s += a * noise(p); p *= 2.03; a *= 0.5; }
  return s;
}
vec3 aces(vec3 x) {
  return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
}

void main() {
  vec3 N = normalize(vN);
  vec3 L = normalize(uSun);
  vec3 V = normalize(uCam - vWorld);
  vec3 H = normalize(L + V);

  // процедурный материал: шум в мировых координатах + мелкое зерно
  float n1 = fbm(vWorld * 1.7);
  float n2 = noise(vWorld * 14.0);
  vec3 albedo = vColor * (0.70 + 0.55 * n1) * (0.92 + 0.16 * n2);

  // швы плит на верхних гранях
  if (N.y > 0.5) {
    vec2 g = abs(fract(vWorld.xz * 0.5) - 0.5);
    float line = 1.0 - smoothstep(0.0, 0.025, min(g.x, g.y));
    albedo *= 1.0 - 0.28 * line;
  }

  // затемнение у рёбер (имитация окклюзии)
  vec3 q = abs(vLocal) / vHalf * (1.0 - abs(N));
  float edge = max(q.x, max(q.y, q.z));
  float ao = 1.0 - 0.30 * smoothstep(0.80, 1.0, edge);
  // у основания объектов темнее
  ao *= mix(0.78, 1.0, smoothstep(0.0, 1.2, vWorld.y + 0.2));

  float diff = max(dot(N, L), 0.0);
  float rough = mix(0.35, 0.9, n1);
  float shin = mix(90.0, 12.0, rough);
  float spec = pow(max(dot(N, H), 0.0), shin) * (1.0 - rough) * 0.8 * diff;
  float fres = pow(1.0 - max(dot(N, V), 0.0), 4.0) * 0.12;

  vec3 sunCol = vec3(1.0, 0.92, 0.78) * 2.6;
  vec3 amb = mix(vec3(0.22, 0.19, 0.16), vec3(0.34, 0.48, 0.72), N.y * 0.5 + 0.5) * 0.75;
  vec3 col = albedo * (sunCol * diff + amb) * ao + vec3(1.0, 0.95, 0.85) * spec * 2.0;
  col += vec3(0.5, 0.65, 0.9) * fres * ao;

  // туман в цвет горизонта
  float d = length(uCam - vWorld);
  float f = 1.0 - exp(-d * d * uFogS);
  col = mix(col, vec3(0.78, 0.85, 0.95), f);

  col = aces(col);
  col = pow(col, vec3(1.0 / 2.2));
  col += (fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233))) * 43758.5453) - 0.5) / 255.0;
  o = vec4(col, 1.0);
}
)";

const char* VS_SKY = R"(#version 300 es
out vec2 vN;
void main() {
  vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
  vN = p * 2.0 - 1.0;
  gl_Position = vec4(vN, 1.0, 1.0);
}
)";

const char* FS_SKY = R"(#version 300 es
precision highp float;
in vec2 vN;
uniform vec3 uF, uR, uU, uSun;
uniform vec2 uTan;
out vec4 o;
vec3 aces(vec3 x) {
  return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
}
void main() {
  vec3 dir = normalize(uF + uR * (vN.x * uTan.x) + uU * (vN.y * uTan.y));
  vec3 horizon = vec3(0.78, 0.85, 0.95);
  vec3 zenith = vec3(0.16, 0.36, 0.78);
  vec3 c = mix(horizon, zenith, pow(clamp(dir.y, 0.0, 1.0), 0.45));
  c = mix(c, vec3(0.50, 0.55, 0.58), clamp(-dir.y * 3.0, 0.0, 1.0));
  float s = max(dot(dir, normalize(uSun)), 0.0);
  c += vec3(1.0, 0.85, 0.6) * (pow(s, 900.0) * 10.0 + pow(s, 10.0) * 0.30);
  c = aces(c);
  c = pow(c, vec3(1.0 / 2.2));
  o = vec4(c, 1.0);
}
)";

const char* VS_HUD = R"(#version 300 es
uniform vec4 uRect;
uniform vec2 uRes;
out vec2 vUV;
void main() {
  vec2 p = vec2(float(gl_VertexID & 1), float(gl_VertexID >> 1));
  vUV = p * 2.0 - 1.0;
  vec2 px = uRect.xy + p * uRect.zw;
  gl_Position = vec4(px.x / uRes.x * 2.0 - 1.0, 1.0 - px.y / uRes.y * 2.0, 0.0, 1.0);
}
)";

const char* FS_HUD = R"(#version 300 es
precision mediump float;
in vec2 vUV;
uniform vec4 uCol;
uniform float uRing;
out vec4 o;
void main() {
  float d = length(vUV);
  float a = smoothstep(1.0, 0.94, d);
  if (uRing > 0.5) a *= smoothstep(0.84, 0.90, d);
  o = vec4(uCol.rgb, uCol.a * a);
}
)";

GLuint compile(GLenum type, const char* src) {
  GLuint s = glCreateShader(type);
  glShaderSource(s, 1, &src, nullptr);
  glCompileShader(s);
  GLint ok = 0;
  glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
  if (!ok) {
    char log[1024];
    glGetShaderInfoLog(s, sizeof(log), nullptr, log);
    printf("shader error: %s\n", log);
  }
  return s;
}

GLuint makeProgram(const char* vs, const char* fs) {
  GLuint p = glCreateProgram();
  GLuint a = compile(GL_VERTEX_SHADER, vs);
  GLuint b = compile(GL_FRAGMENT_SHADER, fs);
  glAttachShader(p, a);
  glAttachShader(p, b);
  glLinkProgram(p);
  GLint ok = 0;
  glGetProgramiv(p, GL_LINK_STATUS, &ok);
  if (!ok) {
    char log[1024];
    glGetProgramInfoLog(p, sizeof(log), nullptr, log);
    printf("link error: %s\n", log);
  }
  glDeleteShader(a);
  glDeleteShader(b);
  return p;
}

void initGL() {
  progScene = makeProgram(VS_SCENE, FS_SCENE);
  progSky = makeProgram(VS_SKY, FS_SKY);
  progHud = makeProgram(VS_HUD, FS_HUD);
  uVP = glGetUniformLocation(progScene, "uVP");
  uCam = glGetUniformLocation(progScene, "uCam");
  uSun = glGetUniformLocation(progScene, "uSun");
  uFogS = glGetUniformLocation(progScene, "uFogS");
  uSkyF = glGetUniformLocation(progSky, "uF");
  uSkyR = glGetUniformLocation(progSky, "uR");
  uSkyU = glGetUniformLocation(progSky, "uU");
  uSkyTan = glGetUniformLocation(progSky, "uTan");
  uSkySun = glGetUniformLocation(progSky, "uSun");
  uHudRect = glGetUniformLocation(progHud, "uRect");
  uHudRes = glGetUniformLocation(progHud, "uRes");
  uHudCol = glGetUniformLocation(progHud, "uCol");
  uHudRing = glGetUniformLocation(progHud, "uRing");

  // куб (36 вершин: позиция + нормаль)
  std::vector<float> mesh;
  mesh.reserve(36 * 6);
  for (int a = 0; a < 3; a++) {
    for (int s = -1; s <= 1; s += 2) {
      int b = (a + 1) % 3, c = (a + 2) % 3;
      const int cs[4][2] = {{-1, -1}, {1, -1}, {1, 1}, {-1, 1}};
      const int tri[2][3] = {{0, 1, 2}, {0, 2, 3}};
      for (int t = 0; t < 2; t++) {
        for (int k = 0; k < 3; k++) {
          int idx = tri[t][s > 0 ? k : 2 - k];
          float p[3], n[3] = {0, 0, 0};
          p[a] = (float)s;
          p[b] = (float)cs[idx][0];
          p[c] = (float)cs[idx][1];
          n[a] = (float)s;
          mesh.insert(mesh.end(), {p[0], p[1], p[2], n[0], n[1], n[2]});
        }
      }
    }
  }

  glGenVertexArrays(1, &vaoMesh);
  glBindVertexArray(vaoMesh);
  glGenBuffers(1, &vboMesh);
  glBindBuffer(GL_ARRAY_BUFFER, vboMesh);
  glBufferData(GL_ARRAY_BUFFER, mesh.size() * sizeof(float), mesh.data(), GL_STATIC_DRAW);
  glEnableVertexAttribArray(0);
  glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 24, (void*)0);
  glEnableVertexAttribArray(1);
  glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 24, (void*)12);

  glGenBuffers(1, &vboInst);
  glBindBuffer(GL_ARRAY_BUFFER, vboInst);
  glBufferData(GL_ARRAY_BUFFER, g_boxes.size() * 36, nullptr, GL_STREAM_DRAW);
  for (int i = 0; i < 3; i++) {
    glEnableVertexAttribArray(2 + i);
    glVertexAttribPointer(2 + i, 3, GL_FLOAT, GL_FALSE, 36, (void*)(size_t)(i * 12));
    glVertexAttribDivisor(2 + i, 1);
  }
  glGenVertexArrays(1, &vaoEmpty);
  glBindVertexArray(0);
  g_inst.reserve(g_boxes.size() * 9);
}

// ------------------------------------------------------------ физика
bool overlaps(const Box& b) {
  return fabsf(g_pos[0] - b.c[0]) < HS[0] + b.h[0] &&
         fabsf(g_pos[1] - b.c[1]) < HS[1] + b.h[1] &&
         fabsf(g_pos[2] - b.c[2]) < HS[2] + b.h[2];
}

void moveAxis(int axis, float amount) {
  if (amount == 0.0f) return;
  g_pos[axis] += amount;
  for (const Box& b : g_boxes) {
    if (!overlaps(b)) continue;
    if (amount > 0) g_pos[axis] = b.c[axis] - b.h[axis] - HS[axis] - 1e-4f;
    else g_pos[axis] = b.c[axis] + b.h[axis] + HS[axis] + 1e-4f;
    g_vel[axis] = 0;
    if (axis == 1 && amount < 0) g_ground = true;
  }
}

void update(float dt) {
  g_yaw += ((kR ? 1 : 0) - (kL ? 1 : 0)) * 2.2f * dt;
  g_pitch += ((kU ? 1 : 0) - (kDn ? 1 : 0)) * 1.6f * dt;
  g_pitch = std::max(-1.4f, std::min(1.4f, g_pitch));

  float mx = stickX, mf = -stickY;
  if (kA) mx -= 1;
  if (kD) mx += 1;
  if (kW) mf += 1;
  if (kS) mf -= 1;
  float l = sqrtf(mx * mx + mf * mf);
  if (l > 1) { mx /= l; mf /= l; }
  float sy = sinf(g_yaw), cy = cosf(g_yaw);
  float wx = (cy * mx + sy * mf) * SPEED;
  float wz = (sy * mx - cy * mf) * SPEED;

  float k = g_ground ? 14.0f : 4.0f;
  float a = 1.0f - expf(-k * dt);
  g_vel[0] += (wx - g_vel[0]) * a;
  g_vel[2] += (wz - g_vel[2]) * a;
  g_vel[1] -= GRAV * dt;
  if (g_vel[1] < -40) g_vel[1] = -40;

  if (g_ground) g_coyote = 0.12f; else g_coyote -= dt;
  bool jumpHeld = kSpace || jumpId >= 0;
  if (jumpHeld && g_coyote > 0) {
    g_vel[1] = JUMP;
    g_coyote = 0;
    g_ground = false;
  }

  g_ground = false;
  moveAxis(0, g_vel[0] * dt);
  moveAxis(2, g_vel[2] * dt);
  moveAxis(1, g_vel[1] * dt);

  if (g_pos[1] < -30) {
    g_pos[0] = 0; g_pos[1] = 2; g_pos[2] = 0;
    g_vel[0] = g_vel[1] = g_vel[2] = 0;
  }
}

// ------------------------------------------------------------ рендер
void applyResize() {
  cssW = (float)js_width();
  cssH = (float)js_height();
  double dpr = js_dpr();
  if (dpr > 2.0) dpr = 2.0;  // на iPhone dpr=3, но 2 заметно быстрее и почти не хуже
  int pw = std::max(1, (int)(cssW * dpr * g_scale));
  int ph = std::max(1, (int)(cssH * dpr * g_scale));
  if (pw != g_pw || ph != g_ph) {
    g_pw = pw; g_ph = ph;
    emscripten_set_canvas_element_size("#canvas", pw, ph);
  }
  g_needResize = false;
}

void circle(float cx, float cy, float r, float R, float G, float B, float A, float ring) {
  glUniform4f(uHudRect, cx - r, cy - r, 2 * r, 2 * r);
  glUniform4f(uHudCol, R, G, B, A);
  glUniform1f(uHudRing, ring);
  glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
}

void render() {
  float asp = (float)g_pw / (float)g_ph;
  float th = 0.70f;
  if (asp < 1.3f) th = 0.70f * 1.3f / asp;
  if (th > 2.5f) th = 2.5f;

  Vec3 eye = {g_pos[0], g_pos[1] + EYE, g_pos[2]};
  Vec3 f = {sinf(g_yaw) * cosf(g_pitch), sinf(g_pitch), -cosf(g_yaw) * cosf(g_pitch)};
  Vec3 right, up;
  Mat4 view = lookDir(eye, f, {0, 1, 0}, &right, &up);
  Mat4 proj = perspective(th, asp, 0.1f, 400.0f);
  Mat4 vp = mul(proj, view);

  // плоскости frustum (Gribb-Hartmann)
  float pl[6][4];
  const float* m = vp.m;
  for (int i = 0; i < 3; i++) {
    for (int s = 0; s < 2; s++) {
      float sg = s == 0 ? 1.0f : -1.0f;
      float* p = pl[i * 2 + s];
      p[0] = m[3] + sg * m[i];
      p[1] = m[7] + sg * m[4 + i];
      p[2] = m[11] + sg * m[8 + i];
      p[3] = m[15] + sg * m[12 + i];
      float len = sqrtf(p[0] * p[0] + p[1] * p[1] + p[2] * p[2]);
      for (int k = 0; k < 4; k++) p[k] /= len;
    }
  }

  g_inst.clear();
  int visible = 0;
  for (const Box& b : g_boxes) {
    bool in = true;
    for (int i = 0; i < 6; i++) {
      float d = pl[i][0] * b.c[0] + pl[i][1] * b.c[1] + pl[i][2] * b.c[2] + pl[i][3];
      if (d < -b.rad) { in = false; break; }
    }
    if (!in) continue;
    g_inst.insert(g_inst.end(), {b.c[0], b.c[1], b.c[2], b.h[0], b.h[1], b.h[2], b.col[0], b.col[1], b.col[2]});
    visible++;
  }

  glViewport(0, 0, g_pw, g_ph);
  glClear(GL_DEPTH_BUFFER_BIT);

  // небо
  glDisable(GL_DEPTH_TEST);
  glDisable(GL_CULL_FACE);
  glUseProgram(progSky);
  glUniform3f(uSkyF, f.x, f.y, f.z);
  glUniform3f(uSkyR, right.x, right.y, right.z);
  glUniform3f(uSkyU, up.x, up.y, up.z);
  glUniform2f(uSkyTan, th * asp, th);
  glUniform3f(uSkySun, g_sun.x, g_sun.y, g_sun.z);
  glBindVertexArray(vaoEmpty);
  glDrawArrays(GL_TRIANGLES, 0, 3);

  // мир: один instanced draw-call
  glEnable(GL_DEPTH_TEST);
  glEnable(GL_CULL_FACE);
  glUseProgram(progScene);
  glUniformMatrix4fv(uVP, 1, GL_FALSE, vp.m);
  glUniform3f(uCam, eye.x, eye.y, eye.z);
  glUniform3f(uSun, g_sun.x, g_sun.y, g_sun.z);
  glUniform1f(uFogS, 0.00006f);
  glBindVertexArray(vaoMesh);
  glBindBuffer(GL_ARRAY_BUFFER, vboInst);
  glBufferData(GL_ARRAY_BUFFER, g_boxes.size() * 36, nullptr, GL_STREAM_DRAW);  // orphaning
  if (visible > 0) {
    glBufferSubData(GL_ARRAY_BUFFER, 0, g_inst.size() * sizeof(float), g_inst.data());
    glDrawArraysInstanced(GL_TRIANGLES, 0, 36, visible);
  }

  // интерфейс
  glDisable(GL_DEPTH_TEST);
  glDisable(GL_CULL_FACE);
  glEnable(GL_BLEND);
  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
  glUseProgram(progHud);
  glUniform2f(uHudRes, cssW, cssH);
  glBindVertexArray(vaoEmpty);
  if (moveId >= 0) {
    circle(stickOX, stickOY, 70, 1, 1, 1, 0.55f, 1);
    circle(stickOX + stickX * 70, stickOY + stickY * 70, 28, 1, 1, 1, 0.45f, 0);
  } else {
    circle(110, cssH - 130, 70, 1, 1, 1, 0.22f, 1);
  }
  circle(cssW - 90, cssH - 110, 52, 1, 1, 1, jumpId >= 0 ? 0.55f : 0.28f, 0);
  circle(cssW - 90, cssH - 110, 52, 1, 1, 1, 0.55f, 1);
  circle(cssW * 0.5f, cssH * 0.5f, 3, 1, 1, 1, 0.7f, 0);
  glDisable(GL_BLEND);
}

// ------------------------------------------------------------ главный цикл
void frame(void*) {
  double now = emscripten_get_now();
  double dt = (now - g_last) / 1000.0;
  g_last = now;
  if (dt > 0.1) dt = 0.1;
  if (dt < 0) dt = 0;
  g_acc += dt;
  while (g_acc >= STEP) { update(STEP); g_acc -= STEP; }

  // динамическое разрешение
  g_avg += (dt - g_avg) * 0.05;
  g_frame++;
  if (g_frame % 45 == 0) {
    if (g_avg > 0.021 && g_scale > 0.5f) { g_scale -= 0.1f; g_lastScaleChange = now; g_needResize = true; }
    else if (g_avg < 0.0175 && g_scale < 1.0f && now - g_lastScaleChange > 4000.0) { g_scale = std::min(1.0f, g_scale + 0.05f); g_lastScaleChange = now; g_needResize = true; }
  }
  if (g_frame % 20 == 0) {
    if ((int)cssW != js_width() || (int)cssH != js_height()) g_needResize = true;
  }
  if (g_needResize) applyResize();
  render();
}

// ------------------------------------------------------------ ввод
EM_BOOL onTouch(int type, const EmscriptenTouchEvent* e, void*) {
  for (int i = 0; i < e->numTouches; i++) {
    const EmscriptenTouchPoint& t = e->touches[i];
    if (!t.isChanged) continue;
    float x = (float)t.clientX, y = (float)t.clientY;
    int id = t.identifier;
    if (type == EMSCRIPTEN_EVENT_TOUCHSTART) {
      float dx = x - (cssW - 90), dy = y - (cssH - 110);
      if (dx * dx + dy * dy < 75 * 75 && jumpId < 0) {
        jumpId = id;
      } else if (x < cssW * 0.5f && moveId < 0) {
        moveId = id; stickOX = x; stickOY = y; stickX = stickY = 0;
      } else if (lookId < 0) {
        lookId = id; lastLX = x; lastLY = y;
      }
    } else if (type == EMSCRIPTEN_EVENT_TOUCHMOVE) {
      if (id == moveId) {
        float dx = (x - stickOX) / 70.0f, dy = (y - stickOY) / 70.0f;
        float l = sqrtf(dx * dx + dy * dy);
        if (l > 1) { dx /= l; dy /= l; }
        stickX = dx; stickY = dy;
      } else if (id == lookId) {
        g_yaw += (x - lastLX) * 0.0055f;
        g_pitch -= (y - lastLY) * 0.0055f;
        g_pitch = std::max(-1.4f, std::min(1.4f, g_pitch));
        lastLX = x; lastLY = y;
      }
    } else {  // end / cancel
      if (id == moveId) { moveId = -1; stickX = stickY = 0; }
      if (id == lookId) lookId = -1;
      if (id == jumpId) jumpId = -1;
    }
  }
  return EM_TRUE;
}

EM_BOOL onKey(int type, const EmscriptenKeyboardEvent* e, void*) {
  bool down = type == EMSCRIPTEN_EVENT_KEYDOWN;
  const char* c = e->code;
  bool handled = true;
  if (!strcmp(c, "KeyW")) kW = down;
  else if (!strcmp(c, "KeyA")) kA = down;
  else if (!strcmp(c, "KeyS")) kS = down;
  else if (!strcmp(c, "KeyD")) kD = down;
  else if (!strcmp(c, "Space")) kSpace = down;
  else if (!strcmp(c, "ArrowLeft")) kL = down;
  else if (!strcmp(c, "ArrowRight")) kR = down;
  else if (!strcmp(c, "ArrowUp")) kU = down;
  else if (!strcmp(c, "ArrowDown")) kDn = down;
  else handled = false;
  return handled ? EM_TRUE : EM_FALSE;
}

EM_BOOL onResize(int, const EmscriptenUiEvent*, void*) {
  g_needResize = true;
  return EM_FALSE;
}

}  // namespace

int main() {
  EmscriptenWebGLContextAttributes a;
  emscripten_webgl_init_context_attributes(&a);
  a.majorVersion = 2;
  a.minorVersion = 0;
  a.alpha = false;
  a.depth = true;
  a.stencil = false;
  a.antialias = false;  // MSAA дорого на мобильных; рёбра сглаживает динамическое разрешение
  a.powerPreference = EM_WEBGL_POWER_PREFERENCE_HIGH_PERFORMANCE;
  g_ctx = emscripten_webgl_create_context("#canvas", &a);
  if (g_ctx <= 0) {
    printf("WebGL2 недоступен\n");
    return 1;
  }
  emscripten_webgl_make_context_current(g_ctx);

  g_sun = normalize({0.5f, 0.7f, 0.35f});
  buildWorld();
  initGL();
  applyResize();

  emscripten_set_touchstart_callback("#canvas", nullptr, EM_TRUE, onTouch);
  emscripten_set_touchmove_callback("#canvas", nullptr, EM_TRUE, onTouch);
  emscripten_set_touchend_callback("#canvas", nullptr, EM_TRUE, onTouch);
  emscripten_set_touchcancel_callback("#canvas", nullptr, EM_TRUE, onTouch);
  emscripten_set_keydown_callback(EMSCRIPTEN_EVENT_TARGET_DOCUMENT, nullptr, EM_TRUE, onKey);
  emscripten_set_keyup_callback(EMSCRIPTEN_EVENT_TARGET_DOCUMENT, nullptr, EM_TRUE, onKey);
  emscripten_set_resize_callback(EMSCRIPTEN_EVENT_TARGET_WINDOW, nullptr, EM_FALSE, onResize);

  g_last = emscripten_get_now();
  emscripten_set_main_loop_arg(frame, nullptr, 0, 1);
  return 0;
}
