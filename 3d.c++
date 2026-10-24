#include "raylib.h"
#include <cmath>

int main() {
    // Инициализация окна под мобильное/веб разрешение (адаптивный ландшафт)
    const int screenWidth = 1280;
    const int screenHeight = 720;
    InitWindow(screenWidth, screenHeight, "3D Tactical Shooter - Mobile & Web Optimized");
    SetTargetFPS(60);

    // Настройка камеры (от первого лица, тактический стиль)
    Camera3D camera = { 0 };
    camera.position = (Vector3){ 0.0f, 2.0f, 4.0f };
    camera.target = (Vector3){ 0.0f, 2.0f, 0.0f };
    camera.up = (Vector3){ 0.0f, 1.0f, 0.0f };
    camera.fovy = 65.0f;
    camera.projection = CAMERA_PERSPECTIVE;

    // Переменные для сенсорного управления (тач / мышь)
    Vector2 touchPos = { 0 };
    bool isTouching = false;
    float cameraYaw = 0.0f;
    float cameraPitch = 0.0f;

    // Игровой мир / Враги (мишени)
    Vector3 targetPos = { 0.0f, 1.5f, -10.0f };
    bool targetAlive = true;
    int score = 0;

    while (!WindowShouldClose()) {
        // --- 1. ОПТИМИЗИРОВАННОЕ СЕНСОРНОЕ УПРАВЛЕНИЕ ---
        // Поддерживает как касания пальцем на планшете/телефоне, так и мышь на ПК
        bool activeTouch = (GetTouchPointCount() > 0) || IsMouseButtonDown(MOUSE_BUTTON_LEFT);
        
        if (activeTouch) {
            Vector2 currentTouch = (GetTouchPointCount() > 0) ? GetTouchPosition(0) : GetMousePosition();
            
            // Игнорируем зону виртуальной кнопки стрельбы справа снизу
            if (currentTouch.x < (float)(screenWidth - 160) || currentTouch.y < (float)(screenHeight - 160)) {
                if (!isTouching) {
                    touchPos = currentTouch;
                    isTouching = true;
                } else {
                    // Плавный поворот камеры свайпом
                    float deltaX = (currentTouch.x - touchPos.x) * 0.003f;
                    float deltaY = (currentTouch.y - touchPos.y) * 0.003f;

                    cameraYaw -= deltaX;
                    cameraPitch -= deltaY;

                    // Ограничение угла наклона по вертикали
                    if (cameraPitch > 1.2f) cameraPitch = 1.2f;
                    if (cameraPitch < -1.2f) cameraPitch = -1.2f;

                    touchPos = currentTouch;
                }
            }
        } else {
            isTouching = false;
        }

        // Расчет направления взгляда камеры (вектор направления)
        camera.target = (Vector3){
            camera.position.x + sinf(cameraYaw) * cosf(cameraPitch),
            camera.position.y + sinf(cameraPitch),
            camera.position.z + cosf(cameraYaw) * cosf(cameraPitch)
        };

        // Авто-перемещение вперед или по кнопке W
        if (IsKeyDown(KEY_W) || IsKeyDown(KEY_UP)) {
            camera.position.x += sinf(cameraYaw) * 0.06f;
            camera.position.z += cosf(cameraYaw) * 0.06f;
        }

        // Проверка нажатия кнопки стрельбы (тач по кнопке "FIRE")
        if (IsMouseButtonPressed(MOUSE_BUTTON_LEFT)) {
            Vector2 mPos = GetMousePosition();
            if (mPos.x > screenWidth - 150 && mPos.y > screenHeight - 150) {
                if (targetAlive) {
                    targetAlive = false; // Уничтожение цели
                    score += 100;
                }
            }
        }

        // --- 2. ОТРИСОВКА ГРАФИКИ ---
        BeginDrawing();
        ClearBackground((Color){ 15, 23, 42, 255 }); // Стильный темно-синий ночной фон (Cyber/Tactical theme)

        BeginMode3D(camera);

            // Тактическая сетка арены
            DrawGrid(25, 1.0f);

            // Укрытия и стены (low-poly геометрия для максимальной оптимизации)
            DrawCube((Vector3){ -6.0f, 1.0f, -6.0f }, 2.5f, 2.0f, 2.5f, (Color){ 30, 41, 59, 255 });
            DrawCubeWires((Vector3){ -6.0f, 1.0f, -6.0f }, 2.5f, 2.0f, 2.5f, (Color){ 51, 65, 85, 255 });

            DrawCube((Vector3){ 6.0f, 1.0f, -9.0f }, 3.0f, 2.5f, 2.0f, (Color){ 30, 41, 59, 255 });
            DrawCubeWires((Vector3){ 6.0f, 1.0f, -9.0f }, 3.0f, 2.5f, 2.0f, (Color){ 51, 65, 85, 255 });

            // Враг / Мишень
            if (targetAlive) {
                DrawCube(targetPos, 1.2f, 1.8f, 0.8f, (Color){ 239, 68, 68, 255 }); // Ярко-красный акцент
                DrawCubeWires(targetPos, 1.2f, 1.8f, 0.8f, (Color){ 254, 202, 202, 255 });
            }

            // Оружие от первого лица (привязано к камере с покачиванием)
            float bobbing = sinf(GetTime() * 10.0f) * 0.02f * (IsKeyDown(KEY_W) ? 1.0f : 0.0f);
            Vector3 gunPos = { 
                camera.position.x + sinf(cameraYaw + 0.35f) * 0.4f, 
                camera.position.y - 0.35f + bobbing, 
                camera.position.z + cosf(cameraYaw + 0.35f) * 0.4f 
            };
            DrawCube(gunPos, 0.12f, 0.12f, 0.55f, (Color){ 15, 23, 42, 255 });

        EndMode3D();

        // --- 3. ИНТЕРФЕЙС И УПРАВЛЕНИЕ НА ЭКРАНЕ (HUD) ---
        // Центральный прицел
        DrawCircle(screenWidth / 2, screenHeight / 2, 3, (Color){ 52, 211, 153, 220 });
        DrawCircleLines(screenWidth / 2, screenHeight / 2, 7, (Color){ 255, 255, 255, 120 });

        // Виртуальная кнопка стрельбы для телефона/планшета
        DrawRectangle(screenWidth - 140, screenHeight - 140, 110, 110, (Color){ 239, 68, 68, 160 });
        DrawRectangleLines(screenWidth - 140, screenHeight - 140, 110, 110, (Color){ 255, 255, 255, 200 });
        DrawText("FIRE", screenWidth - 105, screenHeight - 90, 22, WHITE);

        // Статистика и очки
        DrawText(TextFormat("SCORE: %04d", score), 20, 20, 20, (Color){ 52, 211, 153, 255 });
        DrawText("SWIPE to Look | W to Move", 20, 50, 16, (Color){ 148, 163, 184, 255 });
        DrawFPS(screenWidth - 100, 20);

        EndDrawing();
    }

    CloseWindow();
    return 0;
}
