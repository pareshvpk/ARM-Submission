-keep class org.pytorch.executorch.** { *; }
-keep class com.facebook.soloader.** { *; }
-keep class com.facebook.jni.** { *; }

# Keep every class that declares native methods: R8 cannot see the JNI side, so a
# renamed or removed class breaks the lookup at run time.
-keepclasseswithmembernames class * {
    native <methods>;
}

# org.ps3.sentinel: checked on 2026-11-21, no class is loaded by name (no
# Class.forName), annotated @Keep, or declares external fun / native methods in
# src/main, so no app-specific keep rule is needed. Add one here if that changes.

# Classes the ExecuTorch AAR references by annotation but does not ship.
-dontwarn javax.annotation.**
-dontwarn com.facebook.infer.annotation.**
